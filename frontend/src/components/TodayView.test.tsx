import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TodayView, dueFromParse, orderEntries, weekStartOf } from './TodayView'
import { DataProvider } from '../data'
import {
  cacheDayPlan, cacheDayRange, cacheHabits,
  readCachedDayPlan, readCachedHabits, setCacheUser,
} from '../cache'
import {
  api, uidFor,
  type CalEvent, type DayEntry, type DayEntrySource, type DayPlan, type Habit,
  type List, type Task,
} from '../api'

// The whole API module, like every other component suite here: each method
// becomes a vi.fn(), so nothing touches the network and the day endpoints can
// be driven directly. The shared matchMedia stub comes from src/test/setup.ts —
// a local one would be inert and would shadow it for the rest of the file.
vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})

const m = vi.mocked(api)

const pad = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
/** The key the view will compute for itself, read at call time so a suite that
 *  moves the clock still agrees with it. */
const today = () => ymd(new Date())
const inDays = (n: number) => {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return ymd(d)
}

const list: List = {
  id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 1, task_count: 1, event_count: 0, total: 1, color: '#D9480F',
}
const cal: List = {
  id: 'c1', href: '/c1/', name: 'Personal', is_task_list: false, is_calendar: true,
  open_count: 0, task_count: 0, event_count: 1, total: 1, color: '#1971C2',
}

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [], parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
  created: null, last_modified: null,
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

const entry = (o: Partial<DayEntry> = {}): DayEntry => ({
  entry_id: 'e1', day: today(), kind: 'note', list: null, uid: null,
  title: 'Water the plants', source: 'user', position: 1,
  done_at: null, dropped_at: null, habit_id: null, estimate_minutes: null,
  rolled_to: null, worked_seconds: null, capped: null,
  created_at: '2026-08-21T08:00:00.000Z', ...o,
})

/** One occurrence of a habit: an ORDINARY day-plan row, which is the whole
 *  design — kind and source say where it came from, `habit_id` is the identity
 *  the week is counted under, and `title` is the copy taken from the rule when
 *  the row was minted. */
const occurrence = (o: Partial<DayEntry> = {}): DayEntry => entry({
  entry_id: 'h-today', kind: 'habit', source: 'habit', habit_id: 'hb1',
  title: 'Read', position: 0, ...o,
})

const habit = (o: Partial<Habit> = {}): Habit => ({
  id: 'hb1', title: 'Read', days: '', paused_at: null, position: 1,
  estimate_minutes: null, created_at: '2026-08-01T08:00:00.000Z', ...o,
})

/** One calendar event, the same shape `CalendarView.test.tsx` builds. Defined
 *  here rather than imported so this suite stays readable on its own, and kept
 *  field-for-field with that one so a widened `CalEvent` breaks both together
 *  rather than only the file someone happened to open. */
const calEvent = (o: Partial<CalEvent> = {}): CalEvent => ({
  uid: 'ev1', id: 'ev1', recurrence_id: null, is_recurring: false, calendar: '/c1/',
  summary: 'Standup', description: null, location: null,
  start: `${today()}T09:00:00`, start_is_date: false,
  end: `${today()}T10:30:00`, end_is_date: false, duration: null,
  all_day: false, status: null, busy: true, notify_minutes_before: null, tags: [], has_rrule: false,
  href: '/c1/ev1.ics', etag: '"1"', ...o,
})

const plan = (entries: DayEntry[] = [], day = today(), o: Partial<DayPlan> = {}): DayPlan =>
  // Nothing said about the day by default, and `capacity: null` in particular:
  // an account that never stated one must be the ordinary case in this suite,
  // so a test that wants a total has to ask for it.
  ({
    day, planned: true, entries,
    capacity_minutes: null, capacity: null,
    committed_at: null, shutdown_at: null, reflection: null, ...o,
  })

/** A promise left in flight, and the function that lands it.
 *
 *  What every "before the server answers" assertion below needs: a call held
 *  open long enough to read what is on the screen while it is still pending.
 *  `vi.fn()` with no implementation resolves immediately, which is exactly the
 *  frame these tests are not about. */
const held = <T,>() => {
  let land: (v: T) => void = () => {}
  let fail: (e: unknown) => void = () => {}
  const promise = new Promise<T>((res, rej) => { land = res; fail = rej })
  return { promise, land: (v: T) => land(v), fail: (e: unknown) => fail(e) }
}

/** `opts` reaches `userEvent.setup` untouched. The only caller that passes
 *  anything is a fake-timer suite: userEvent's own delays are `setTimeout`s, so
 *  under a frozen clock they never resolve unless it is told how to move one. */
function setup(opts: Parameters<typeof userEvent.setup>[0] = {}) {
  render(
    <DataProvider rev={0} onExpire={vi.fn()}>
      <TodayView rev={0} onExpire={vi.fn()} />
    </DataProvider>,
  )
  return userEvent.setup(opts)
}

/** The day's own rows (not the suggestion lists, which reuse the row class).
 *  Habit occurrences are excluded too: they are day rows, but they paint in
 *  their own group above the day and `habitTitles` below reads that one. */
const dayRows = () =>
  [...document.querySelectorAll('.today-row:not(.today-sug):not(.today-habit)')]
const rowTitles = () =>
  dayRows().map((r) => r.querySelector('.today-title')?.textContent ?? '')

/** The add box's consequence line — "will add Task/Note …".
 *
 *  Read by the id `aria-describedby` points at, not by a role: it is
 *  deliberately NOT a live region (it is on for every keystroke now, so it
 *  would announce on every keystroke), and the id is the contract that ties it
 *  to the input it describes. Querying it this way fails if that tie is broken.
 */
const fateChip = () => document.getElementById('today-add-fate')

/** The habits group's rows, read through the list's accessible name rather than
 *  through the row class, so this fails if the group stops being a named group
 *  and not merely if a class is renamed. */
const habitTitles = () =>
  [...(screen.queryByRole('list', { name: 'Habits' })?.querySelectorAll('.today-title') ?? [])]
    .map((t) => t.textContent ?? '')

beforeEach(() => {
  vi.clearAllMocks()
  setCacheUser('')
  localStorage.clear()
  m.lists.mockResolvedValue([list])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.openDay.mockResolvedValue(plan())
  // The pure read, which is the ONLY call the picker makes for a day that is
  // not today. It answers an empty plan FOR THE DAY IT WAS ASKED ABOUT: a
  // fixture that answered today's key would be filtered out by the view (the
  // rows on screen and the day they belong to have to match) and every
  // look-back assertion would pass vacuously against a blank screen.
  m.day.mockImplementation(async (d) => plan([], d))
  // The fortnight behind the habit counts and the "still open" suggestion, and
  // the habit definitions the sheet edits. Both default to empty so every suite
  // that is not about them sees the surface exactly as it was before they
  // existed.
  m.days.mockResolvedValue([])
  m.habits.mockResolvedValue([])
  m.createHabit.mockImplementation(async (body) =>
    habit({ id: 'hb-new', title: body.title, days: body.days ?? '' }))
  // Spelled out field by field rather than spread, because the wire shapes
  // differ where it matters: the body carries `paused`, a boolean, and the
  // habit carries `paused_at`, a stamp. A mock that echoed the body back would
  // hand the component a field the real endpoint never sends.
  m.patchHabit.mockImplementation(async (id, body) => habit({
    id,
    ...(body.title !== undefined ? { title: body.title } : {}),
    ...(body.days !== undefined ? { days: body.days } : {}),
    paused_at: body.paused ? '2026-08-21T10:00:00.000Z' : null,
  }))
  m.deleteHabit.mockResolvedValue(null)
  m.patchDayEntry.mockImplementation(async (_d, id) => entry({ entry_id: id }))
  // The roll answers the SOURCE entry stamped with where it went — the target
  // row is created on another day and never reaches this view. A mock that
  // answered the target would hide the one local change the writer makes.
  m.rollDayEntry.mockImplementation(async (_d, id, to) =>
    entry({ entry_id: id, rolled_to: to }))
  m.addDayEntry.mockImplementation(async (d, body) => entry({
    entry_id: body.entry_id, day: d, kind: body.kind,
    list: body.list ?? null, uid: body.uid ?? null, title: body.title ?? null,
    position: 9,
  }))
})

// ── the snapshot ────────────────────────────────────────────────────────────

describe('<TodayView> the day', () => {
  it('opens the day on mount and renders its entries in position order', async () => {
    m.tasks.mockResolvedValue([task({ uid: 'u1', summary: 'Ship it' })])
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'b', position: 2, title: 'Second' }),
      entry({ entry_id: 'a', position: 1, kind: 'task', list: 'l1', uid: 'u1', title: null }),
    ]))
    setup()

    // POST, not GET: opening is the only call allowed to build a snapshot.
    await waitFor(() => expect(m.openDay).toHaveBeenCalledWith(today()))
    expect(m.day).not.toHaveBeenCalled()
    await waitFor(() => expect(rowTitles()).toEqual(['Ship it', 'Second']))
  })

  it('never renders an entry the day recorded as dropped', async () => {
    // The server stamps rather than deletes, so a dropped row comes back on
    // every read — it is the day's record of a decision, not a live row.
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'a', title: 'Kept' }),
      entry({ entry_id: 'b', title: 'Declined', dropped_at: '2026-08-21T10:00:00.000Z' }),
    ]))
    setup()
    await waitFor(() => expect(rowTitles()).toEqual(['Kept']))
  })

  it('says nothing at all until the first open lands', async () => {
    let settle: (p: DayPlan) => void = () => {}
    m.openDay.mockReturnValue(new Promise((r) => { settle = r }) as never)
    setup()
    // An empty state flashed before the fetch would read as "your day is
    // empty" about a day nobody has looked at yet.
    expect(screen.queryByText(/nothing on today yet/i)).not.toBeInTheDocument()
    await act(async () => { settle(plan()) })
    expect(await screen.findByText(/nothing on today yet/i)).toBeInTheDocument()
  })
})

// ── which side of the fence each truth lives on ─────────────────────────────

describe('<TodayView> checking a row', () => {
  it('routes a task row through the task API, never through the day', async () => {
    m.tasks.mockResolvedValue([task({ uid: 'u1', summary: 'Ship it' })])
    m.complete.mockResolvedValue(task({ uid: 'u1', completed: true }))
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'a', kind: 'task', list: 'l1', uid: 'u1', title: null }),
    ]))
    const user = setup()
    await screen.findByText('Ship it')

    await user.click(screen.getByRole('button', { name: /check ship it/i }))

    // A task's truth is its VTODO STATUS. Recording it on the day entry as well
    // would be a second answer to one question, and the two would disagree the
    // moment the task was ticked in the Tasks pane or on a phone.
    await waitFor(() => expect(m.complete).toHaveBeenCalledWith('l1', 'u1', true))
    expect(m.patchDayEntry).not.toHaveBeenCalled()
  })

  it('toggles a note on the day entry itself', async () => {
    m.openDay.mockResolvedValue(plan([entry({ entry_id: 'n1', title: 'Water the plants' })]))
    m.patchDayEntry.mockResolvedValue(
      entry({ entry_id: 'n1', done_at: '2026-08-21T10:00:00.000Z' }))
    const user = setup()
    await screen.findByText('Water the plants')

    await user.click(screen.getByRole('button', { name: /check water the plants/i }))

    // A note exists nowhere but in the day, so the day is the only place its
    // doneness can live.
    await waitFor(() =>
      expect(m.patchDayEntry).toHaveBeenCalledWith(today(), 'n1', { done: true }))
    expect(m.complete).not.toHaveBeenCalled()
    await waitFor(() => expect(dayRows()[0].className).toContain('done'))
  })

  it('un-ticks a note that is already done', async () => {
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'n1', done_at: '2026-08-21T10:00:00.000Z' }),
    ]))
    const user = setup()
    await screen.findByText('Water the plants')
    await user.click(screen.getByRole('button', { name: /uncheck water the plants/i }))
    await waitFor(() =>
      expect(m.patchDayEntry).toHaveBeenCalledWith(today(), 'n1', { done: false }))
  })
})

describe('<TodayView> dropping a row', () => {
  it('takes it off the day and out of view', async () => {
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'n1', title: 'Water the plants' }),
      entry({ entry_id: 'n2', title: 'Ring the bank', position: 2 }),
    ]))
    const user = setup()
    await screen.findByText('Water the plants')

    await user.click(screen.getByRole('button', { name: /remove water the plants/i }))

    await waitFor(() =>
      expect(m.patchDayEntry).toHaveBeenCalledWith(today(), 'n1', { dropped: true }))
    await waitFor(() => expect(rowTitles()).toEqual(['Ring the bank']))
  })

  it('puts the row back when the drop does not land', async () => {
    m.openDay.mockResolvedValue(plan([entry({ entry_id: 'n1', title: 'Water the plants' })]))
    m.patchDayEntry.mockRejectedValue(new Error('nope'))
    const user = setup()
    await screen.findByText('Water the plants')

    await user.click(screen.getByRole('button', { name: /remove water the plants/i }))

    // A UI that keeps a row hidden after the write failed is claiming a
    // decision the record does not hold.
    await waitFor(() => expect(m.patchDayEntry).toHaveBeenCalled())
    await waitFor(() => expect(rowTitles()).toEqual(['Water the plants']))
  })
})

// ── the midnight rollover ───────────────────────────────────────────────────

describe('<TodayView> midnight', () => {
  afterEach(() => { vi.useRealTimers() })

  it('re-opens the new day when the clock crosses local midnight', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date(2026, 7, 21, 23, 59, 0))
    m.openDay.mockImplementation(async (d: string) => plan(
      d === '2026-08-21' ? [entry({ entry_id: 'y', day: d, title: 'Yesterday' })] : [],
      d,
    ))
    setup()
    await waitFor(() => expect(m.openDay).toHaveBeenCalledWith('2026-08-21'))
    await waitFor(() => expect(rowTitles()).toEqual(['Yesterday']))

    await act(async () => { vi.advanceTimersByTime(61_000) })

    // The whole point: a surface left open overnight moves to the new day by
    // itself. Without it every write would still carry 2026-08-21 in its URL.
    await waitFor(() => expect(m.openDay).toHaveBeenCalledWith('2026-08-22'))
    // …and yesterday's rows go with it, rather than sitting under today's
    // heading where ticking one would rewrite a finished day.
    await waitFor(() => expect(rowTitles()).toEqual([]))
  })

  it('carries the NEW day key in a write made after the rollover', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date(2026, 7, 21, 23, 59, 0))
    m.openDay.mockImplementation(async (d: string) => plan(
      [entry({ entry_id: `e-${d}`, day: d, title: 'Water the plants' })], d))
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TodayView rev={0} onExpire={vi.fn()} />
      </DataProvider>,
    )
    await waitFor(() => expect(m.openDay).toHaveBeenCalledWith('2026-08-21'))

    await act(async () => { vi.advanceTimersByTime(61_000) })
    await waitFor(() => expect(m.openDay).toHaveBeenCalledWith('2026-08-22'))

    await user.click(await screen.findByRole('button', { name: /check water the plants/i }))
    await waitFor(() =>
      expect(m.patchDayEntry).toHaveBeenCalledWith('2026-08-22', 'e-2026-08-22', { done: true }))
  })

  it('clears the timer on unmount', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date(2026, 7, 21, 23, 59, 0))
    const { unmount } = render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TodayView rev={0} onExpire={vi.fn()} />
      </DataProvider>,
    )
    await waitFor(() => expect(m.openDay).toHaveBeenCalledTimes(1))
    unmount()
    await act(async () => { vi.advanceTimersByTime(61_000) })
    // A timer left armed on an unmounted component sets state on it, and would
    // keep the whole view (and its data closure) alive for the page's lifetime.
    expect(m.openDay).toHaveBeenCalledTimes(1)
  })
})

// ── the day picker ──────────────────────────────────────────────────────────

/** Step the picker one day back. */
const back = async (user: ReturnType<typeof userEvent.setup>) =>
  user.click(await screen.findByRole('button', { name: 'Previous day' }))

describe('<TodayView> the day picker', () => {
  it('READS a past day and never opens one', async () => {
    m.day.mockImplementation(async (d) =>
      plan([entry({ entry_id: `e-${d}`, day: d, title: 'Yesterday' })], d))
    const user = setup()
    await waitFor(() => expect(m.openDay).toHaveBeenCalledTimes(1))

    await back(user)

    // THE test of this stage. `openDay` is the only call that can CREATE a
    // plan, and on a day that has never been opened it derives a snapshot from
    // the wire as it is NOW — so pointing it at a day that has already happened
    // invents a record the owner never made. Stepping back must therefore raise
    // the `day` count and leave the `openDay` count exactly where it was.
    await waitFor(() => expect(m.day).toHaveBeenCalledWith(inDays(-1)))
    expect(m.openDay).toHaveBeenCalledTimes(1)
    expect(m.openDay).not.toHaveBeenCalledWith(inDays(-1))
    // And the rows on screen are that day's, not the ones today was holding.
    expect(await screen.findByText('Yesterday')).toBeInTheDocument()
  })

  it('hands out nothing that could change a past day', async () => {
    m.tasks.mockResolvedValue([task({ uid: 'a', summary: 'Due today', due: today() })])
    m.day.mockImplementation(async (d) =>
      plan([entry({ entry_id: 'n1', day: d, title: 'Water the plants' })], d))
    const user = setup()
    // The control: every one of these is on the screen for today.
    expect(await screen.findByLabelText('Add to today')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Add Due today to today' }))
      .toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Habits' })).toBeInTheDocument()

    await back(user)
    await screen.findByText('Water the plants')

    // A past day is READ-ONLY end to end, the same line `update_day_entry`
    // draws for the connector: a tick is a record that something was done AT
    // THE TIME, and one that can be filled in afterwards is worth nothing.
    expect(screen.queryByLabelText('Add to today')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /to today$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^check /i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^uncheck /i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^remove /i })).not.toBeInTheDocument()
    // The habits sheet writes rules, and its whole feedback loop is the day
    // behind it — which a past day cannot show.
    expect(screen.queryByRole('button', { name: 'Habits' })).not.toBeInTheDocument()
    // …and the heading says which of the two screens this is.
    expect(screen.getByText('Look back')).toBeInTheDocument()
  })

  it('leaves the habits sheet behind when the day moves', async () => {
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Habits' }))
    expect(await screen.findByRole('dialog', { name: 'Habits' })).toBeInTheDocument()

    // The OPENER is gated on today; the sheet itself was not, so one opened on
    // today outlived the step back. `.overlay` blocks the pointer and nothing
    // else — there is no focus trap in this dialog — so Tab reaches this very
    // button from inside the sheet and Enter presses it, leaving a writable
    // dialog standing over a screen headed "Look back".
    await user.click(screen.getByRole('button', { name: 'Previous day' }))

    expect(screen.queryByRole('dialog', { name: 'Habits' })).not.toBeInTheDocument()
    // Gone, not merely unreachable: everything inside it is out of the tab order
    // too, which is the half a `pointer-events` scrim was never going to give.
    expect(screen.queryByLabelText('New habit')).not.toBeInTheDocument()

    // Coming home brings it back, and that is the intended reading rather than
    // an oversight: the gate is about what a FINISHED DAY may paint, and the
    // owner never closed the sheet. One flag, one gate — clearing it on the way
    // past as well would be a second answer to the same question.
    await user.click(screen.getByRole('button', { name: 'Today' }))
    expect(await screen.findByRole('dialog', { name: 'Habits' })).toBeInTheDocument()
  })

  it('comes back to today, and the day is workable again', async () => {
    m.day.mockImplementation(async (d) =>
      plan([entry({ entry_id: `e-${d}`, day: d, title: 'Yesterday' })], d))
    m.openDay.mockResolvedValue(plan([entry({ entry_id: 'n1', title: 'Water the plants' })]))
    const user = setup()
    await back(user)
    await waitFor(() => expect(screen.queryByLabelText('Add to today')).not.toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Today' }))

    expect(await screen.findByLabelText('Add to today')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Check Water the plants' }))
      .toBeInTheDocument()
    expect(screen.getByText('Today')).toBeInTheDocument()
  })

  it('stops at the look-back floor, and never offers a future day', async () => {
    const user = setup()
    await screen.findByLabelText('Add to today')
    // Today is the ceiling: the Today tab is not a planner for next month, and
    // a future day could be shown but never opened.
    expect(screen.getByRole('button', { name: 'Next day' })).toBeDisabled()

    // One step past the floor, to prove the last click is the one that does
    // nothing rather than the loop simply running out.
    for (let i = 0; i < 15; i += 1) {
      await user.click(screen.getByRole('button', { name: 'Previous day' }))
    }

    await waitFor(() => expect(m.day).toHaveBeenCalledWith(inDays(-14)))
    expect(m.day).not.toHaveBeenCalledWith(inDays(-15))
    expect(screen.getByRole('button', { name: 'Previous day' })).toBeDisabled()
  })
})

describe('<TodayView> midnight with a past day on screen', () => {
  afterEach(() => { vi.useRealTimers() })

  it('leaves the view where the owner put it', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date(2026, 7, 21, 23, 59, 0))
    m.day.mockImplementation(async (d) =>
      plan([entry({ entry_id: `e-${d}`, day: d, title: 'Yesterday' })], d))
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TodayView rev={0} onExpire={vi.fn()} />
      </DataProvider>,
    )
    await waitFor(() => expect(m.openDay).toHaveBeenCalledWith('2026-08-21'))
    await back(user)
    await waitFor(() => expect(m.day).toHaveBeenCalledWith('2026-08-20'))

    await act(async () => { vi.advanceTimersByTime(61_000) })

    // The timer still tracks TODAY — that is what the rest of the surface is
    // measured against — but the view only follows it when it was showing
    // today. Someone reviewing Thursday at 23:59 must not find Saturday under
    // their cursor.
    expect(screen.getByText(/August 20/)).toBeInTheDocument()
    // And above all: the day that rolled in was never opened from here. The
    // view is parked on a past day, so the read stays a read.
    expect(m.openDay).not.toHaveBeenCalledWith('2026-08-22')
    expect(m.openDay).toHaveBeenCalledTimes(1)
  })
})

// ── the look-back ───────────────────────────────────────────────────────────

describe('<TodayView> what a reviewed day shows', () => {
  /** The titles in one named group of the look-back. */
  const inGroup = (name: string) =>
    [...(screen.queryByRole('list', { name })?.querySelectorAll('.today-title') ?? [])]
      .map((t) => t.textContent)

  it('splits the day by where each row came from', async () => {
    m.tasks.mockResolvedValue([task({ uid: 'u1', summary: 'Ship it' })])
    m.day.mockImplementation(async (d) => plan([
      entry({
        entry_id: 'a', day: d, position: 1, title: 'Chose this', source: 'user',
        done_at: `${d}T12:00:00.000Z`,
      }),
      entry({ entry_id: 'b', day: d, position: 2, title: 'From Monday', source: 'carried' }),
      entry({
        entry_id: 'c', day: d, position: 3, kind: 'task', list: 'l1', uid: 'u1',
        title: null, source: 'auto',
      }),
      occurrence({ entry_id: 'd', day: d, position: 4 }),
      entry({
        entry_id: 'e', day: d, position: 5, title: 'Declined', source: 'user',
        dropped_at: `${d}T18:00:00.000Z`,
      }),
      // A source this build has never heard of. The residual arm exists for
      // exactly this and matches `review_day`'s `other`: an unrecognised source
      // that matched no arm is how habit occurrences fell out of the tool's
      // retrospective in silence, which is the bug this rules out on the
      // browser side.
      entry({
        entry_id: 'f', day: d, position: 6, title: 'Something new',
        source: 'sideways' as DayEntrySource,
      }),
    ], d))
    const user = setup()

    await back(user)

    await waitFor(() => expect(inGroup('Chosen')).toEqual(['Chose this']))
    expect(inGroup('Carried over')).toEqual(['From Monday'])
    // A task entry still reads its title live off the task it points at.
    expect(inGroup('Derived')).toEqual(['Ship it'])
    expect(inGroup('Habits')).toEqual(['Read'])
    expect(inGroup('Other')).toEqual(['Something new'])
    // Dropped is its own arm and is NOT bucketed by source — "planned it and
    // decided against it" is one answer whatever put the row there — so this
    // source="user" row is here and NOT under Chosen, which the first
    // assertion pins.
    expect(inGroup('Dropped')).toEqual(['Declined'])

    // Whether a row was DONE is the single most important thing a look-back
    // says about it, and a strike-through says it to sighted readers only. The
    // one row that was ticked carries a named mark; the five that were not
    // carry nothing, because "not done" is the absence of it and announcing it
    // on every row would bury the rows that have one.
    const marks = screen.getAllByRole('img', { name: 'Done' })
    expect(marks).toHaveLength(1)
    expect(marks[0].closest('.today-row')?.querySelector('.today-title')?.textContent)
      .toBe('Chose this')
    // A declined row is marked as one on the row itself, so it still reads as
    // declined outside its heading's context.
    expect(screen.getByText('Declined').closest('.today-row')?.className)
      .toContain('today-dropped')

    // "3 open" is a to-do list's figure and belongs on the day you can still
    // act on; a finished day is better counted the other way up. Both halves
    // are over the LIVE rows — five here, the dropped one having its own
    // heading — which is why this is 1 of 5 and not 1 of 6.
    expect(screen.getByText(/1 done · 5 on the day/)).toBeInTheDocument()
  })

  it('shows what was finished that day and never planned', async () => {
    const y = inDays(-1)
    m.tasks.mockResolvedValue([
      task({ uid: 'u1', summary: 'Wrote the thing', completed: true,
        completed_at: `${y}T15:04:00` }),
      task({ uid: 'u2', summary: 'Was on the plan', completed: true,
        completed_at: `${y}T16:00:00` }),
      task({ uid: 'u3', summary: 'Finished today', completed: true,
        completed_at: `${today()}T09:00:00` }),
    ])
    m.day.mockImplementation(async (d) => plan([
      entry({
        entry_id: 'a', day: d, kind: 'task', list: 'l1', uid: 'u2', title: null,
        source: 'user',
      }),
    ], d))
    const user = setup()

    await back(user)

    // The half that is usually the more interesting one, and the half that
    // answers for days before any of this existed: it comes off the VTODO's own
    // COMPLETED stamp rather than off the plan.
    await waitFor(() => expect(inGroup('Done off-plan')).toEqual(['Wrote the thing']))
    // Already painted under Chosen — one task under two contradictory headings
    // is worse than either.
    expect(inGroup('Chosen')).toEqual(['Was on the plan'])
    // A different day's completion belongs to that day.
    expect(inGroup('Done off-plan')).not.toContain('Finished today')
    // These rows are the one thing on the screen that definitely happened, and
    // they say so the same way a ticked entry does.
    const off = within(screen.getByRole('list', { name: 'Done off-plan' }))
    expect(off.getByRole('img', { name: 'Done' })).toBeInTheDocument()
    // The clock, not the date: the date is the heading of the whole screen.
    expect(off.getByText(/3:04|15:04/)).toBeInTheDocument()
  })

  it('orders what was finished off-plan by WHEN, newest first', async () => {
    const y = inDays(-1)
    // Summaries deliberately in an alphabetical order that is NOT the order they
    // were finished in. None carries a due date or a priority, so `sortTasks` —
    // due, then priority, then summary, then uid, none of them `completed_at` —
    // prints them Alpha, Bravo, Charlie, Delta and their clocks as 8:44, 9:11,
    // 5:33, 1:22: a day's times of day in what reads as no order at all, on a
    // list whose only content besides the title IS the clock.
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Alpha', completed: true, completed_at: `${y}T20:44:00` }),
      task({ uid: 'b', summary: 'Bravo', completed: true, completed_at: `${y}T09:11:00` }),
      task({ uid: 'c', summary: 'Charlie', completed: true, completed_at: `${y}T17:33:00` }),
      task({ uid: 'd', summary: 'Delta', completed: true, completed_at: `${y}T13:22:00` }),
    ])
    const user = setup()

    await back(user)

    // `sortByCompletion`, the helper HomeView's "recently completed" module and
    // the Tasks pane's completed view already share — every task here has a
    // stamp by construction, so every one lands in its newest-first branch.
    await waitFor(() => expect(inGroup('Done off-plan'))
      .toEqual(['Alpha', 'Charlie', 'Delta', 'Bravo']))
    // The clock is what a reader actually scans down, so the rendered times are
    // pinned and not merely the titles. Read by MINUTE, so the assertion holds
    // under either the 12- or the 24-hour setting.
    const clocks = [...screen.getByRole('list', { name: 'Done off-plan' })
      .querySelectorAll('.today-due')].map((n) => n.textContent?.match(/:(\d\d)/)?.[1])
    expect(clocks).toEqual(['44', '33', '22', '11'])
  })

  it('buckets the completion stamp by day key, not by slicing the string', async () => {
    // 02:00 UTC on the 21st is 22:00 on the 20th in America/New_York (the zone
    // this suite runs in, from vite.config.ts). Slicing the first ten
    // characters files it on the 21st; `dayKey` — the rule the rest of the app
    // buckets by, and the rule `_completions_by_day` applies server-side —
    // files it on the 20th, where the owner actually did it.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date(2026, 7, 21, 9, 0))
    try {
      m.tasks.mockResolvedValue([
        task({ uid: 'u1', summary: 'Late one', completed: true,
          completed_at: '2026-08-21T02:00:00Z' }),
      ])
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      render(
        <DataProvider rev={0} onExpire={vi.fn()}>
          <TodayView rev={0} onExpire={vi.fn()} />
        </DataProvider>,
      )
      await back(user)
      await waitFor(() => expect(m.day).toHaveBeenCalledWith('2026-08-20'))
      await waitFor(() => expect(inGroup('Done off-plan')).toEqual(['Late one']))
    } finally {
      vi.useRealTimers()
    }
  })

  it('says so when the day holds nothing at all', async () => {
    const user = setup()
    await back(user)
    // A day nobody opened has no plan and no rows, and that is a real answer
    // rather than a missing one — `api.day` returns planned=false for it.
    expect(await screen.findByText(/nothing was planned on this day/i)).toBeInTheDocument()
  })

  it('says nothing at all until the read for that day lands', async () => {
    let settle: (p: DayPlan) => void = () => {}
    m.day.mockReturnValue(new Promise((r) => { settle = r }) as never)
    const user = setup()
    await back(user)
    // On a look-back the empty state IS the whole content of the screen, so
    // flashing it over a fetch in flight is a claim about a day the surface has
    // not seen yet.
    expect(screen.queryByText(/nothing was planned on this day/i)).not.toBeInTheDocument()
    await act(async () => { settle(plan([], inDays(-1))) })
    expect(await screen.findByText(/nothing was planned on this day/i)).toBeInTheDocument()
  })
})

// ── was it done THAT day? ───────────────────────────────────────────────────

describe('<TodayView> whether a row was done ON the day', () => {
  it('marks a task row only if its completion falls on the day being read', async () => {
    m.tasks.mockResolvedValue([
      // Finished at 22:00 local on the day under review, written as 02:00Z the
      // morning after — the shape a client that anchors the stamp to a zone
      // sends. Slicing the first ten characters files it on the wrong day;
      // `dayKey` files it where the owner actually did it, which is the rule
      // `offPlan` and `_completions_by_day` already apply.
      task({ uid: 'u1', summary: 'Filed on the day', completed: true,
        completed_at: `${today()}T02:00:00Z` }),
      // THE bug, and the scenario two reviewers gave for it: planned on the day
      // under review, not done, ticked days later. The task's live flag says
      // done — but not on this day, and this day's record must not claim a
      // completion that happened after it ended.
      task({ uid: 'u2', summary: 'File taxes', completed: true,
        completed_at: `${today()}T09:00:00` }),
      // Done on the day and RE-OPENED since. Re-opening clears the COMPLETED
      // property (`ical/edit.py::_set_status`) and a task entry deliberately
      // keeps no done state of its own, so nothing anywhere still records that
      // completion. No mark is the honest answer — the conservative direction,
      // and the only one the data supports — rather than an accepted loss.
      task({ uid: 'u3', summary: 'Was done, then re-opened', completed: false,
        completed_at: null }),
    ])
    m.day.mockImplementation(async (d) => plan([
      entry({ entry_id: 'a', day: d, position: 1, kind: 'task', list: 'l1', uid: 'u1',
        title: null, source: 'user' }),
      entry({ entry_id: 'b', day: d, position: 2, kind: 'task', list: 'l1', uid: 'u2',
        title: null, source: 'user' }),
      entry({ entry_id: 'c', day: d, position: 3, kind: 'task', list: 'l1', uid: 'u3',
        title: null, source: 'user' }),
    ], d))
    const user = setup()

    await back(user)
    await screen.findByText('File taxes')

    // One mark, on the one row that was actually finished on this day.
    const marks = screen.getAllByRole('img', { name: 'Done' })
    expect(marks.map(
      (n) => n.closest('.today-row')?.querySelector('.today-title')?.textContent))
      .toEqual(['Filed on the day'])
    // …and the header agrees, because it counts through the same call. Before
    // this rule existed both ticked tasks were "done" here and the day claimed
    // two completions, one of which happened after it.
    expect(screen.getByText(/1 done · 3 on the day/)).toBeInTheDocument()
  })

  it('still reads TODAY off the live flag, where a stamp may not exist yet', async () => {
    // Completed, with a stamp belonging to another day — the shape of a task
    // ticked elsewhere and still sitting on today's plan, and (with no stamp at
    // all) of a client that never writes COMPLETED. Today asks the VTODO's flag
    // and nothing else: a tick made a moment ago has to show on the click, and
    // its stamp is not back from the server yet.
    m.tasks.mockResolvedValue([task({
      uid: 'u1', summary: 'Ship it', completed: true,
      completed_at: `${inDays(-3)}T09:00:00`,
    })])
    m.openDay.mockResolvedValue(plan([entry({
      entry_id: 'a', kind: 'task', list: 'l1', uid: 'u1', title: null,
    })]))
    setup()

    expect(await screen.findByRole('button', { name: 'Uncheck Ship it' }))
      .toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText(/0 open · 1 on the day/)).toBeInTheDocument()
  })
})

// ── suggestions ─────────────────────────────────────────────────────────────

describe('<TodayView> suggestions', () => {
  it('offers due-today, overdue and upcoming tasks, excluding what is on the day', async () => {
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Due today', due: today() }),
      task({ uid: 'b', summary: 'Already planned', due: today() }),
      task({ uid: 'c', summary: 'Late', due: inDays(-3) }),
      task({ uid: 'd', summary: 'Soon', due: inDays(3) }),
      task({ uid: 'e', summary: 'Far off', due: inDays(30) }),
      task({ uid: 'f', summary: 'Someday' }),
    ])
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'x', kind: 'task', list: 'l1', uid: 'b', title: null }),
    ]))
    setup()
    await screen.findByText('Already planned')

    const add = (name: string) => screen.queryByRole('button', { name: `Add ${name} to today` })
    await waitFor(() => expect(add('Due today')).toBeInTheDocument())
    expect(add('Late')).toBeInTheDocument()
    expect(add('Soon')).toBeInTheDocument()
    // Already on the day — offering it again is two "add" buttons for one row.
    expect(add('Already planned')).not.toBeInTheDocument()
    // Outside the seven-day horizon, and undated work is chosen from the Tasks
    // pane rather than suggested here.
    expect(add('Far off')).not.toBeInTheDocument()
    expect(add('Someday')).not.toBeInTheDocument()
  })

  it('gives tomorrow its own heading, out of the seven-day block', async () => {
    // Tomorrow is the one future day a plan for today is routinely about — the
    // thing pulled forward because this afternoon is free, or looked at to
    // decide whether it can wait. Inside a list headed "Next seven days" it was
    // a row like any other, six days out of context.
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Due today', due: today() }),
      task({ uid: 'b', summary: 'Tomorrow thing', due: inDays(1) }),
      task({ uid: 'c', summary: 'Thursday thing', due: inDays(3) }),
    ])
    m.openDay.mockResolvedValue(plan([]))
    setup()
    await screen.findByRole('button', { name: 'Add Tomorrow thing to today' })

    const headings = [...document.querySelectorAll('.section-label')].map((n) => n.textContent)
    expect(headings).toContain('Due tomorrow')
    // Between the day's own business and the horizon: what the day is
    // answerable for above, what is coming below.
    expect(headings.indexOf('Due tomorrow'))
      .toBeGreaterThan(headings.indexOf('Due today'))
    expect(headings.indexOf('Due tomorrow'))
      .toBeLessThan(headings.indexOf('Next seven days'))
  })

  it('does not offer tomorrow twice', async () => {
    // The horizon predicate is still `> day`, so tomorrow matches it too — the
    // `offered` set is what keeps the two apart, exactly as it does for a task
    // that is both due today and overdue from 09:01. Two headings offering one
    // task is two "add" buttons for one row, and the first press makes the
    // second a no-op the user cannot explain.
    m.tasks.mockResolvedValue([
      task({ uid: 'b', summary: 'Tomorrow thing', due: inDays(1) }),
    ])
    m.openDay.mockResolvedValue(plan([]))
    setup()
    await screen.findByRole('button', { name: 'Add Tomorrow thing to today' })

    expect(screen.getAllByRole('button', { name: 'Add Tomorrow thing to today' }))
      .toHaveLength(1)
    // And with nothing else in the window, the horizon group is absent rather
    // than present and empty.
    const headings = [...document.querySelectorAll('.section-label')].map((n) => n.textContent)
    expect(headings).not.toContain('Next seven days')
  })

  it('offers back a task the day recorded as DROPPED, but not one it MOVED', async () => {
    // The two stamps are different answers and this is the one place the
    // difference shows. "I decided against this" leaves the task undecided
    // about, and the server's add is idempotent EXCEPT over dropped rows for
    // precisely that reason — choosing it again this afternoon has to work.
    // "This is happening on Thursday" already put a row on another day, so
    // offering it back under "Due today" would contradict the decision.
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Declined', due: today() }),
      task({ uid: 'b', summary: 'Moved on', due: today() }),
    ])
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'x', kind: 'task', list: 'l1', uid: 'a', title: null,
        dropped_at: `${today()}T10:00:00.000Z` }),
      entry({ entry_id: 'y', kind: 'task', list: 'l1', uid: 'b', title: null,
        rolled_to: inDays(1) }),
    ]))
    setup()
    const add = (name: string) => screen.queryByRole('button', { name: `Add ${name} to today` })
    await waitFor(() => expect(add('Declined')).toBeInTheDocument())
    expect(add('Moved on')).not.toBeInTheDocument()
  })

  it('never offers one task under two headings', async () => {
    // A task due at 09:00 today is both `dayKey(due) === today` AND overdue
    // from 09:01. Two buttons for one task means the second press is a no-op
    // the user cannot explain.
    const at9 = `${today()}T09:00:00`
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Standup notes', due: at9, due_is_date: false }),
    ])
    setup()
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: /add standup notes to today/i }))
        .toHaveLength(1))
  })

  it('does not re-offer work an earlier day MOVED to another day', async () => {
    // The one reader of `rolled_to` the column did not reach when it was added.
    // "Still open from a recent plan" is for work that was chosen and never
    // decided about — and a row with a DESTINATION has been decided about: the
    // work already has a row on the day it went to. Without this, something the
    // owner sent to Thursday during Monday's shutdown came back on Tuesday
    // under "you did not finish these last time", which is the plan offering
    // back the answer it was given forty seconds earlier.
    //
    // The contrast is a row still sitting undecided on that earlier day, which
    // is precisely what this group is FOR — so the assertion says the group
    // still works rather than merely that it went quiet.
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Moved on' }),
      task({ uid: 'b', summary: 'Still open' }),
    ])
    m.days.mockResolvedValue([plan([
      entry({
        entry_id: 'p1', day: inDays(-3), kind: 'task', list: 'l1', uid: 'a',
        title: null, source: 'user', rolled_to: inDays(-1),
      }),
      entry({
        entry_id: 'p2', day: inDays(-3), kind: 'task', list: 'l1', uid: 'b',
        title: null, source: 'user',
      }),
    ], inDays(-3))])
    setup()

    const add = (name: string) => screen.queryByRole('button', { name: `Add ${name} to today` })
    await waitFor(() => expect(add('Still open')).toBeInTheDocument())
    expect(add('Moved on')).not.toBeInTheDocument()
  })

  it('offers what was chosen on an earlier day and never finished', async () => {
    // The gap the carry deliberately leaves. `service._carry_into` moves a
    // source="user" row forward exactly ONCE — "a task the owner chose on
    // Monday and then ignored on Tuesday has been declined, and following them
    // all week is how a plan turns into a list nobody reads" — so from
    // Wednesday on an undated task like this one is in no group at all. This is
    // that task offered back as a QUESTION rather than put on the day.
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Slipped' }),
      task({ uid: 'b', summary: 'Chose and did it', completed: true }),
      task({ uid: 'c', summary: 'Turned up on its own' }),
      task({ uid: 'd', summary: 'Never chosen' }),
    ])
    m.days.mockResolvedValue([plan([
      entry({
        entry_id: 'p1', day: inDays(-3), kind: 'task', list: 'l1', uid: 'a',
        title: null, source: 'user',
      }),
      entry({
        entry_id: 'p2', day: inDays(-3), kind: 'task', list: 'l1', uid: 'b',
        title: null, source: 'user',
      }),
      // source="auto" and source="carried" rows are NOT a choice the owner
      // made: the snapshot derived them, and they re-derive themselves from the
      // wire every morning if they still qualify.
      entry({
        entry_id: 'p3', day: inDays(-3), kind: 'task', list: 'l1', uid: 'c',
        title: null, source: 'auto',
      }),
    ], inDays(-3))])
    setup()

    const add = (name: string) => screen.queryByRole('button', { name: `Add ${name} to today` })
    await waitFor(() => expect(add('Slipped')).toBeInTheDocument())
    expect(screen.getByText('Still open from a recent plan')).toBeInTheDocument()
    // Chosen and finished: it is not still open.
    expect(add('Chose and did it')).not.toBeInTheDocument()
    expect(add('Turned up on its own')).not.toBeInTheDocument()
    expect(add('Never chosen')).not.toBeInTheDocument()
    // Still ONE range read, feeding this and the habit counts both.
    expect(m.days).toHaveBeenCalledTimes(1)
  })

  it('reads only EARLIER days as a recent plan, even before today has landed',
    async () => {
      // The one range read spans up to and including today, and it can land
      // BEFORE the open does. Today is not "a recent plan" — it is the plan —
      // and without that guard its own user rows would be read as still open
      // for as long as the open took, so the owner would watch a task offered
      // back to them a moment before it appeared on the day above.
      let settle: (p: DayPlan) => void = () => {}
      m.openDay.mockReturnValue(new Promise((r) => { settle = r }) as never)
      m.tasks.mockResolvedValue([
        task({ uid: 'a', summary: 'Already planned' }),
        task({ uid: 'b', summary: 'Slipped' }),
      ])
      const onToday = entry({
        entry_id: 'x', kind: 'task', list: 'l1', uid: 'a', title: null, source: 'user',
      })
      m.days.mockResolvedValue([
        plan([onToday]),
        plan([entry({
          entry_id: 'p1', day: inDays(-3), kind: 'task', list: 'l1', uid: 'b',
          title: null, source: 'user',
        })], inDays(-3)),
      ])
      setup()

      // The control, and the wait: the group is on screen, built from the same
      // range read, so the absence below is a decision rather than a race.
      expect(await screen.findByRole('button', { name: 'Add Slipped to today' }))
        .toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Add Already planned to today' }))
        .not.toBeInTheDocument()

      // And once the day itself lands it is `onDay` that keeps it out, which is
      // the same answer by the ordinary route.
      await act(async () => { settle(plan([onToday])) })
      expect(await screen.findByText('Already planned')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Add Already planned to today' }))
        .not.toBeInTheDocument()
    })

  it('stops offering a slipped task once it is back on the day', async () => {
    m.tasks.mockResolvedValue([task({ uid: 'a', summary: 'Slipped' })])
    m.days.mockResolvedValue([plan([
      entry({
        entry_id: 'p1', day: inDays(-3), kind: 'task', list: 'l1', uid: 'a',
        title: null, source: 'user',
      }),
    ], inDays(-3))])
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'x', kind: 'task', list: 'l1', uid: 'a', title: null }),
    ]))
    setup()

    await screen.findByText('Slipped')
    // On the day, so not offered — the same rule the three dated groups keep.
    expect(screen.queryByRole('button', { name: 'Add Slipped to today' }))
      .not.toBeInTheDocument()
    expect(screen.queryByText('Still open from a recent plan')).not.toBeInTheDocument()
  })

  it('offers an undated task that nothing has touched in weeks', async () => {
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Forgotten', last_modified: `${inDays(-40)}T09:00:00` }),
      task({ uid: 'b', summary: 'From an old client', created: `${inDays(-40)}T09:00:00` }),
      task({ uid: 'c', summary: 'Touched last week', last_modified: `${inDays(-5)}T09:00:00` }),
      task({
        uid: 'd', summary: 'Old but dated', due: inDays(60),
        last_modified: `${inDays(-40)}T09:00:00`,
      }),
      task({ uid: 'e', summary: 'No stamps at all' }),
    ])
    setup()

    const add = (name: string) => screen.queryByRole('button', { name: `Add ${name} to today` })
    await waitFor(() => expect(add('Forgotten')).toBeInTheDocument())
    // The heading carries the number, built from the constant so the words and
    // the threshold cannot drift apart.
    expect(screen.getByText('Untouched for 21 days')).toBeInTheDocument()
    // LAST-MODIFIED and CREATED are both optional iCalendar properties, so the
    // second is the fallback for a client that wrote no first.
    expect(add('From an old client')).toBeInTheDocument()
    expect(add('Touched last week')).not.toBeInTheDocument()
    // A DATED task is not neglected, it is scheduled — and the three dated
    // groups are the ones that speak for it. This one is 60 days out, so
    // without the restriction it would appear here and nowhere else, which is
    // precisely the fourth way to surface the same rows this group refuses to
    // be.
    expect(add('Old but dated')).not.toBeInTheDocument()
    // Neither stamp is evidence of neglect; it is the absence of evidence. An
    // account synced from a client that writes neither would otherwise see its
    // entire undated backlog under this heading.
    expect(add('No stamps at all')).not.toBeInTheDocument()
  })

  it('keeps the two new groups disjoint from the dated three, and from each other',
    async () => {
      // Each of these qualifies for TWO groups at once. One "add" button each,
      // under the earlier heading — the first press of a duplicate makes the
      // second a no-op the user cannot explain.
      m.tasks.mockResolvedValue([
        task({
          uid: 'a', summary: 'Late and slipped', due: inDays(-3),
          last_modified: `${inDays(-40)}T09:00:00`,
        }),
        task({ uid: 'b', summary: 'Slipped and stale', last_modified: `${inDays(-40)}T09:00:00` }),
      ])
      m.days.mockResolvedValue([plan([
        entry({
          entry_id: 'p1', day: inDays(-3), kind: 'task', list: 'l1', uid: 'a',
          title: null, source: 'user',
        }),
        entry({
          entry_id: 'p2', day: inDays(-3), kind: 'task', list: 'l1', uid: 'b',
          title: null, source: 'user',
        }),
      ], inDays(-3))])
      setup()

      await waitFor(() => expect(
        screen.getAllByRole('button', { name: 'Add Late and slipped to today' }),
      ).toHaveLength(1))
      expect(screen.getAllByRole('button', { name: 'Add Slipped and stale to today' }))
        .toHaveLength(1)

      /** The heading the task with this name is offered under. */
      const under = (name: string) => screen
        .getByRole('button', { name: `Add ${name} to today` })
        .closest('section')?.querySelector('.section-label')?.textContent

      // A due date is a fact about the task; a plan it fell out of is a fact
      // about a day. The task is better described by the first.
      expect(under('Late and slipped')).toBe('Overdue')
      // And between the two new groups, "you chose this and never did it" is
      // the stronger statement.
      expect(under('Slipped and stale')).toBe('Still open from a recent plan')
    })

  it('offers none of it on a past day', async () => {
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Due today', due: today() }),
      task({ uid: 'b', summary: 'Forgotten', last_modified: `${inDays(-40)}T09:00:00` }),
    ])
    const user = setup()
    await screen.findByRole('button', { name: 'Add Due today to today' })

    await back(user)

    // There is no such thing as adding to last Tuesday, so the whole panel is
    // gone rather than each button being disabled.
    await waitFor(() => expect(screen.queryByText('Due today')).not.toBeInTheDocument())
    expect(screen.queryByText('Untouched for 21 days')).not.toBeInTheDocument()
  })

  it('puts a chosen task on the day', async () => {
    m.tasks.mockResolvedValue([task({ uid: 'a', summary: 'Due today', due: today() })])
    const user = setup()
    await user.click(await screen.findByRole('button', { name: /add due today to today/i }))

    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalledWith(
      today(), expect.objectContaining({ kind: 'task', list: 'l1', uid: 'a' })))
    // …and it stops being a suggestion, because it is now on the day.
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /add due today to today/i }))
        .not.toBeInTheDocument())
    expect(rowTitles()).toEqual(['Due today'])
  })
})

// ── the calendar strip ──────────────────────────────────────────────────────

describe('<TodayView> the calendar', () => {
  it('reports a calendar whose events did not load', async () => {
    // `fetchWindow` uses allSettled, so a failed calendar never rejects, never
    // reaches the error toast, and would otherwise leave the day quietly short.
    m.calendars.mockResolvedValue([cal])
    m.events.mockRejectedValue(new Error('502'))
    setup()
    expect(await screen.findByText(/couldn’t load Personal/i)).toBeInTheDocument()
  })

  it('stays blank about the calendar until the calendars have landed', async () => {
    let settle: (c: List[]) => void = () => {}
    m.calendars.mockReturnValue(new Promise((r) => { settle = r }) as never)
    setup()
    await screen.findByText('On the calendar')
    // `eventsFor` answers [] both for "none" and for "nothing known yet".
    expect(screen.queryByText(/nothing on the calendar today/i)).not.toBeInTheDocument()
    await act(async () => { settle([]) })
    expect(await screen.findByText(/nothing on the calendar today/i)).toBeInTheDocument()
  })
})

// ── the add box ─────────────────────────────────────────────────────────────

describe('<TodayView> the add box', () => {
  it('shows what it read out of the line, as the line is typed', async () => {
    const user = setup()
    await screen.findByLabelText('Add to today')
    await user.type(screen.getByLabelText('Add to today'), 'gym at 7')

    // Read by id rather than by role. The chip is no longer a `role="status"`
    // live region: it used to appear only on the rare line that parsed, and now
    // it is on for every line with a character in it, so announcing itself
    // would mean announcing on every keystroke. It describes the input instead
    // (`aria-describedby`), and the outcome is in the submit button's name.
    await waitFor(() => expect(fateChip()).not.toBeNull())
    const chip = fateChip()!
    expect(within(chip).getByText('gym')).toBeInTheDocument()
    // Rendered through fmtDue with the live 12/24-hour setting, so the chip
    // promises exactly what the row will read.
    expect(chip.textContent).toMatch(/7:00/)
    // The meridiem was inferred, not stated, and the chip says so.
    expect(chip.textContent).toMatch(/guess/i)
  })

  it('commits a parsed line as a real task, and points the day at it', async () => {
    m.createTask.mockResolvedValue(task({ uid: 'new@tasksd', summary: 'gym', due: `${today()}T07:00` }))
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'gym at 7{Enter}')

    // A thing with a due date belongs on a list, where the rest of the account
    // can see it — the day entry only points at it.
    await waitFor(() => expect(m.createTask).toHaveBeenCalledWith(
      'l1', expect.objectContaining({ summary: 'gym', due: `${today()}T07:00` })))
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalledWith(
      today(), expect.objectContaining({ kind: 'task', list: 'l1', uid: 'new@tasksd' })))
    expect(screen.getByLabelText('Add to today')).toHaveValue('')
  })

  it('commits a line it read nothing in as a plain note', async () => {
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'call mum{Enter}')

    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalledWith(
      today(), expect.objectContaining({ kind: 'note', title: 'call mum' })))
    expect(m.createTask).not.toHaveBeenCalled()
  })

  it('declining the reading commits the literal line instead', async () => {
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'gym at 7')
    // The control says what it does now, rather than being a ✕ on a preview.
    await user.click(await screen.findByRole('button', { name: 'Make it a note' }))

    // The chip STAYS, and changes its answer. That is the difference from the
    // old ✕, which simply took the preview away and left the box saying nothing
    // at all about what Enter would do — the silence this whole change removes.
    const chip = fateChip()!
    expect(chip.textContent).toMatch(/Note/)
    expect(chip.textContent).toMatch(/never leaves Smylte/)

    await user.type(screen.getByLabelText('Add to today'), '{Enter}')

    // The phrase the parser would have eaten is still in the text — a note that
    // quietly lost its "at 7" is the silent loss daytext.ts is written around.
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalledWith(
      today(), expect.objectContaining({ kind: 'note', title: 'gym at 7' })))
    expect(m.createTask).not.toHaveBeenCalled()
  })

  it('gives the line back when the add does not land', async () => {
    m.addDayEntry.mockRejectedValue(new Error('nope'))
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'call mum{Enter}')
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByLabelText('Add to today')).toHaveValue('call mum'))
  })
})

// ── the planning ritual ─────────────────────────────────────────────────────

describe('<TodayView> the planning ritual', () => {
  const unplanned = (entries: DayEntry[] = [], capacity: number | null = 300) =>
    plan(entries, today(), { capacity, capacity_minutes: capacity, committed_at: null })

  it('nudges with a band rather than opening itself', async () => {
    // The whole of the prompting. This tab is also the place you glance at to
    // see what is next, and a flow standing in front of that on every first
    // visit is the thing people turn off in week two.
    m.openDay.mockResolvedValue(unplanned([entry({ title: 'Water the plants' })]))
    setup()
    await screen.findByText('Water the plants')

    expect(screen.queryByRole('dialog', { name: 'Plan your day' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Plan my day' })).toBeInTheDocument()
  })

  it('stops nudging once the day has been started', async () => {
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })], today(), {
      capacity: 300, capacity_minutes: 300, committed_at: `${today()}T08:00:00.000Z`,
    }))
    setup()
    await screen.findByText('Water the plants')
    expect(screen.queryByRole('button', { name: 'Plan my day' })).not.toBeInTheDocument()
  })

  it('can be waved away without turning the feature off for good', async () => {
    // Not persisted, and deliberately: it is a nudge about TODAY, and a
    // dismissal that outlived the day would silently disable the ritual on the
    // first impatient morning.
    m.openDay.mockResolvedValue(unplanned([entry({ title: 'Water the plants' })]))
    const user = setup()
    await screen.findByText('Water the plants')
    await user.click(screen.getByRole('button', { name: 'Not now' }))
    expect(screen.queryByRole('button', { name: 'Plan my day' })).not.toBeInTheDocument()
  })

  it('never nudges on a day that has already happened', async () => {
    m.day.mockImplementation(async (d) => plan([entry({ day: d, title: 'Yesterday' })], d))
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Previous day' }))
    await screen.findByText('Yesterday')
    expect(screen.queryByRole('button', { name: 'Plan my day' })).not.toBeInTheDocument()
  })

  it('walks three steps and can be left at any of them', async () => {
    m.openDay.mockResolvedValue(unplanned([entry({ title: 'Water the plants' })]))
    const user = setup()
    await screen.findByText('Water the plants')
    await user.click(screen.getByRole('button', { name: 'Plan my day' }))

    const dialog = await screen.findByRole('dialog', { name: 'Plan your day' })
    expect(within(dialog).getByText('How long is today?')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    expect(within(dialog).getByText('What are you doing?')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    expect(within(dialog).getByText('Shape it')).toBeInTheDocument()

    // Every step is optional and the way out is always there.
    await user.click(within(dialog).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog', { name: 'Plan your day' })).not.toBeInTheDocument()
  })

  it('closes on an Escape dispatched at the window', async () => {
    // `useEscape` binds to the WINDOW — there is no focus trap in these dialogs
    // — so the listener has to answer a key pressed anywhere, not only inside
    // the dialog's own subtree.
    m.openDay.mockResolvedValue(unplanned())
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Plan my day' }))
    await screen.findByRole('dialog', { name: 'Plan your day' })

    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(
      screen.queryByRole('dialog', { name: 'Plan your day' })).not.toBeInTheDocument())
  })

  // ── the picking step ────────────────────────────────────────────────────
  //
  // Nothing below this heading was asserted before. The ritual's tests covered
  // the band, the three-step walk, Escape, the capacity field and the commit —
  // but never opened step two's contents, so the whole reason it is step two
  // (promoting the work you did not finish) was pinned by nothing.

  /** Open the ritual and step to "What are you doing?". */
  const pick = async (user: ReturnType<typeof setup>) => {
    await user.click(screen.getByRole('button', { name: 'Plan my day' }))
    const dialog = await screen.findByRole('dialog', { name: 'Plan your day' })
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    return dialog
  }

  /** A day three days back that chose `uid` and never finished it, which is what
   *  puts a task in the "open" suggestion group. */
  const leftUnfinished = (uid: string) => [plan([
    entry({
      entry_id: `p-${uid}`, day: inDays(-3), kind: 'task', list: 'l1', uid,
      title: null, source: 'user',
    }),
  ], inDays(-3))]

  it('puts what you did not finish at the TOP of the picking step, reworded', async () => {
    // The group the day itself calls "Still open from a recent plan" is written
    // for a quiet list under the day. On the one screen whose whole job is to
    // make you look at it, it says so plainly — and it goes first, above the
    // dated groups that otherwise outrank it.
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Slipped last time' }),
      task({ uid: 'b', summary: 'Due today', due: today(), due_is_date: true }),
    ])
    m.days.mockResolvedValue(leftUnfinished('a'))
    m.openDay.mockResolvedValue(unplanned([]))
    const user = setup()
    await screen.findByRole('button', { name: 'Plan my day' })
    const dialog = await pick(user)

    const headings = [...dialog.querySelectorAll('.section-label')].map((n) => n.textContent)
    expect(headings[0]).toBe('You did not finish these last time')
    // Reworded HERE only — the day behind the dialog keeps its own wording.
    expect(headings).not.toContain('Still open from a recent plan')
    // The rest keep the labels and the order the day gives them: this screen is
    // not a second opinion about what matters, only about what to look at first.
    expect(headings).toContain('Due today')
  })

  it('adds a task to the day from the picking step', async () => {
    m.tasks.mockResolvedValue([task({ uid: 'a', summary: 'Slipped last time' })])
    m.days.mockResolvedValue(leftUnfinished('a'))
    m.openDay.mockResolvedValue(unplanned([]))
    m.addDayEntry.mockResolvedValue(entry({ entry_id: 'new', title: 'Slipped last time' }))
    const user = setup()
    await screen.findByRole('button', { name: 'Plan my day' })
    const dialog = await pick(user)

    await user.click(within(dialog)
      .getByRole('button', { name: 'Add Slipped last time to today' }))
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalledWith(today(),
      expect.objectContaining({ kind: 'task', uid: 'a' })))
  })

  it('says so plainly when there is nothing waiting to be picked', async () => {
    m.tasks.mockResolvedValue([])
    m.openDay.mockResolvedValue(unplanned([]))
    const user = setup()
    await screen.findByRole('button', { name: 'Plan my day' })
    const dialog = await pick(user)
    expect(within(dialog).getByText(/Nothing waiting/)).toBeInTheDocument()
  })

  // ── the running total ───────────────────────────────────────────────────
  //
  // The line that makes the ritual worth walking: the consequence of adding
  // something, in the same breath as the adding. Also asserted by nothing until
  // now — the two `not estimated` assertions elsewhere in this file belong to
  // the shutdown dialog and the day's own load strip.

  const total = (dialog: HTMLElement) => dialog.querySelector('.plan-total')

  it('carries the running total from the second step on', async () => {
    m.openDay.mockResolvedValue(unplanned([
      entry({ entry_id: 'a', title: 'Alpha', estimate_minutes: 90 }),
      entry({ entry_id: 'b', title: 'Bravo', estimate_minutes: 30 }),
    ], 300))
    const user = setup()
    await screen.findByRole('button', { name: 'Plan my day' })
    await user.click(screen.getByRole('button', { name: 'Plan my day' }))
    const dialog = await screen.findByRole('dialog', { name: 'Plan your day' })

    // Absent on step one: the question there is how long today IS, and a total
    // measured against a number still being typed would be answering itself.
    expect(total(dialog)).toBeNull()

    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    expect(total(dialog)).toHaveTextContent('2h of 5h')
    expect(total(dialog)).not.toHaveClass('over')
  })

  it('says how much of the day the total is SILENT about', async () => {
    // Without this the number reads as the whole day when it may be a third of
    // it, and quietly under-reporting is worse than not reporting.
    m.openDay.mockResolvedValue(unplanned([
      entry({ entry_id: 'a', title: 'Alpha', estimate_minutes: 90 }),
      entry({ entry_id: 'b', title: 'Bravo', estimate_minutes: null }),
    ], 300))
    const user = setup()
    await screen.findByRole('button', { name: 'Plan my day' })
    await user.click(screen.getByRole('button', { name: 'Plan my day' }))
    const dialog = await screen.findByRole('dialog', { name: 'Plan your day' })
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    expect(total(dialog)).toHaveTextContent('1h 30m of 5h')
    expect(total(dialog)).toHaveTextContent('1 not estimated')
  })

  it('colours the total and names the overage once it is over', async () => {
    m.openDay.mockResolvedValue(unplanned([
      entry({ entry_id: 'a', title: 'Alpha', estimate_minutes: 400 }),
    ], 300))
    const user = setup()
    await screen.findByRole('button', { name: 'Plan my day' })
    await user.click(screen.getByRole('button', { name: 'Plan my day' }))
    const dialog = await screen.findByRole('dialog', { name: 'Plan your day' })
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    expect(total(dialog)).toHaveTextContent('6h 40m of 5h')
    expect(total(dialog)).toHaveTextContent('1h 40m over')
    // --warn, and the words beside it. The colour is the half that does not
    // survive a screen reader, a greyscale screenshot or a custom theme.
    expect(total(dialog)).toHaveClass('over')
  })

  it('shows no total at all on a day nobody has given a length', async () => {
    // The rule the whole feature turns on: an account that never stated a
    // capacity must not be told it has overcommitted against a number it never
    // gave. There is no honest figure to print, so nothing is printed.
    m.openDay.mockResolvedValue(unplanned([
      entry({ entry_id: 'a', title: 'Alpha', estimate_minutes: 400 }),
    ], null))
    const user = setup()
    await screen.findByRole('button', { name: 'Plan my day' })
    await user.click(screen.getByRole('button', { name: 'Plan my day' }))
    const dialog = await screen.findByRole('dialog', { name: 'Plan your day' })
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    expect(total(dialog)).toBeNull()
  })

  it('takes a capacity in either spelling and stores minutes', async () => {
    m.openDay.mockResolvedValue(unplanned([], null))
    m.patchDay.mockImplementation(async (d, body) =>
      plan([], d, { capacity: body.capacity_minutes ?? null,
        capacity_minutes: body.capacity_minutes ?? null }))
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Plan my day' }))

    await user.type(
      await screen.findByLabelText('How long you are working today'), '5h{Enter}')
    await waitFor(() => expect(m.patchDay).toHaveBeenCalledWith(
      today(), { capacity_minutes: 300 }))
  })

  it('says what it takes when it cannot read the line', async () => {
    // The parser refuses rather than guesses, so the useful half of a rejection
    // is the example — not the word "invalid".
    m.openDay.mockResolvedValue(unplanned([], null))
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Plan my day' }))
    await user.type(
      await screen.findByLabelText('How long you are working today'), 'soonish{Enter}')

    expect(m.patchDay).not.toHaveBeenCalled()
    expect(document.querySelector('.plan-hint.warn')).not.toBeNull()
  })

  it('states the overcommitment at the moment of committing, and commits anyway', async () => {
    // It records a decision rather than enforcing one. A warning that stopped
    // you would be a tool arguing with a call it has no standing to make.
    m.openDay.mockResolvedValue(unplanned(
      [entry({ title: 'Too much', estimate_minutes: 480 })], 300))
    m.patchDay.mockImplementation(async (d) => plan([], d, { committed_at: `${d}T08:00:00Z` }))
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Plan my day' }))
    const dialog = await screen.findByRole('dialog', { name: 'Plan your day' })
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    expect(within(dialog).getByText(/3h more than you said you would work/))
      .toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Start the day' }))
    await waitFor(() => expect(m.patchDay).toHaveBeenCalledWith(
      today(), { committed: true }))
  })
})

// ── the shutdown ritual ─────────────────────────────────────────────────────

describe('<TodayView> the shutdown ritual', () => {
  /** Open the ritual and hand back the dialog. */
  const open = async (user: ReturnType<typeof setup>) => {
    await user.click(await screen.findByRole('button', { name: 'Shut down' }))
    return screen.findByRole('dialog', { name: 'Shut down the day' })
  }

  /** The day's own rows BEHIND the ritual.
   *
   *  `rowTitles()` reads every `.today-row` in the document, and the ritual
   *  renders the day's rows through the day's OWN renderer — which is the point
   *  of that renderer being lifted in, and also why an unscoped read counts
   *  each row twice while a step showing them is open. */
  const pageRows = () => dayRows()
    .filter((r) => !r.closest('.overlay'))
    .map((r) => r.querySelector('.today-title')?.textContent ?? '')

  it('is a button and never a band', async () => {
    // The planning nudge is a band because the morning is when a plan is worth
    // prompting for. A band offering to close the day would be on screen from
    // breakfast onwards, nagging about an evening that has not arrived.
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    setup()
    await screen.findByText('Water the plants')

    expect(screen.queryByRole('dialog', { name: 'Shut down the day' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Shut down' })).toBeInTheDocument()
  })

  it('is absent on a day that has already happened', async () => {
    // `set_day_ritual` refuses a shutdown on a past day, so offering one would
    // be a control that 400s. Absent rather than disabled, like the rest here.
    m.day.mockImplementation(async (d) => plan([entry({ day: d, title: 'Yesterday' })], d))
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Previous day' }))
    await screen.findByText('Yesterday')
    expect(screen.queryByRole('button', { name: 'Shut down' })).not.toBeInTheDocument()
  })

  it('walks three steps and can be left at any of them', async () => {
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    const user = setup()
    await screen.findByText('Water the plants')
    const dialog = await open(user)

    expect(within(dialog).getByText('How today went')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    expect(within(dialog).getByText('What follows you')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    expect(within(dialog).getByText('Anything to note?')).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog', { name: 'Shut down the day' })).not.toBeInTheDocument()
  })

  it('closes on an Escape dispatched at the window', async () => {
    // `useEscape` binds to the WINDOW — there is no focus trap in these dialogs
    // — so the listener has to answer a key pressed anywhere.
    const user = setup()
    await open(user)

    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(
      screen.queryByRole('dialog', { name: 'Shut down the day' })).not.toBeInTheDocument())
  })

  it('states what happened as a fact and never as a score', async () => {
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'a', title: 'Done thing', estimate_minutes: 60,
        done_at: `${today()}T10:00:00.000Z` }),
      entry({ entry_id: 'b', title: 'Open thing', estimate_minutes: 60 }),
    ]))
    const user = setup()
    await screen.findByText('Done thing')
    const dialog = await open(user)

    expect(within(dialog).getByText(/1 of 2 done/)).toBeInTheDocument()
    expect(within(dialog).getByText(/1h of 2h planned/)).toBeInTheDocument()
    // NO VERDICT. The same call the habit count makes: a surface that grades
    // you is a surface you stop opening, and this is the one you would be
    // opening at the end of a hard day.
    expect(dialog.textContent).not.toMatch(/%|streak|well done|good job/i)
  })

  it('counts a task ticked in the Tasks pane as done', async () => {
    // THE REASON `isDone` IS LIFTED IN rather than re-derived here. A task row's
    // doneness is its VTODO's, not the entry's stamp — tick it anywhere else in
    // the app and the entry's `done_at` is still null. Deriving doneness inside
    // the ritual reads that as unfinished, so the day undercounts itself AND
    // offers to move work that is already finished.
    m.tasks.mockResolvedValue([task({ uid: 'u1', summary: 'Ship it', completed: true })])
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'a', kind: 'task', list: 'l1', uid: 'u1', title: null,
        estimate_minutes: 30 }),
    ]))
    const user = setup()
    await screen.findByText('Ship it')
    const dialog = await open(user)

    expect(within(dialog).getByText(/1 of 1 done/)).toBeInTheDocument()
    expect(within(dialog).getByText(/30m of 30m planned/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    expect(within(dialog).getByText(/Everything on today is done/)).toBeInTheDocument()
  })

  it('lists what got finished without ever being planned', async () => {
    // Usually the more interesting half, and the half a plan cannot know.
    m.tasks.mockResolvedValue([task({
      uid: 'u9', summary: 'Fixed the printer', completed: true,
      completed_at: `${today()}T14:00:00.000Z`,
    })])
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    const user = setup()
    await screen.findByText('Water the plants')
    const dialog = await open(user)

    expect(within(within(dialog).getByRole('list', { name: 'Done off-plan' }))
      .getByText('Fixed the printer')).toBeInTheDocument()
  })

  it('names a task row by its task, never by the entry', async () => {
    // FOUND BY LOOKING AT IT. A task entry carries no title of its own — the
    // VTODO's summary is the truth — so a ritual that read `entry.title` printed
    // "(this task)" against every task on the one screen whose entire job is
    // deciding about them. 1030 green tests had nothing to say about it.
    m.tasks.mockResolvedValue([task({ uid: 'u1', summary: 'Send the Q3 invoice' })])
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'a', kind: 'task', list: 'l1', uid: 'u1', title: null }),
    ]))
    const user = setup()
    await screen.findByText('Send the Q3 invoice')
    const dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    expect(within(dialog).getByRole('button',
      { name: 'Move Send the Q3 invoice to tomorrow' })).toBeInTheDocument()
    expect(dialog.textContent).not.toMatch(/\(this task\)/)
  })

  it('says how much of the day the minutes are silent about', async () => {
    // ALSO FOUND BY LOOKING AT IT. When the rows that got done are the ones
    // without estimates, the figure alone reads "0m of 1h 20m planned" — which
    // looks like a day nothing happened on, and a false verdict is exactly what
    // this step must not deliver.
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'a', title: 'Done, unestimated', done_at: `${today()}T10:00:00.000Z` }),
      entry({ entry_id: 'b', title: 'Open, estimated', estimate_minutes: 80 }),
    ]))
    const user = setup()
    await screen.findByText('Done, unestimated')
    const dialog = await open(user)

    expect(within(dialog).getByText(/0m of 1h 20m planned/)).toBeInTheDocument()
    expect(within(dialog).getByText(/1 not estimated/)).toBeInTheDocument()
  })

  it('sends a row to tomorrow, which takes it off today', async () => {
    m.openDay.mockResolvedValue(plan([entry({ entry_id: 'a', title: 'Water the plants' })]))
    const user = setup()
    await screen.findByText('Water the plants')
    const dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    await user.click(within(dialog).getByRole('button',
      { name: 'Move Water the plants to tomorrow' }))
    await waitFor(() => expect(m.rollDayEntry).toHaveBeenCalledWith(today(), 'a', inDays(1)))
    // `rolled_to` is what makes it leave: the day filters moved rows out
    // exactly as it filters dropped ones, so deciding about something takes it
    // out of the day's total as well as out of this list.
    await waitFor(() => expect(pageRows()).toEqual([]))
  })

  it('takes the row off the day at once, and puts it back if the move fails', async () => {
    // The optimistic half, and its undo. Deferred rather than
    // `mockRejectedValue` so the row's DISAPPEARANCE can be observed before the
    // reply lands — with a mock that settles immediately, "it comes back" would
    // pass even if it had never left.
    let fail = (_e: Error) => {}
    m.rollDayEntry.mockImplementation(() => new Promise((_res, rej) => { fail = rej }))
    m.openDay.mockResolvedValue(plan([entry({ entry_id: 'a', title: 'Water the plants' })]))
    const user = setup()
    await screen.findByText('Water the plants')
    const dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    await user.click(within(dialog).getByRole('button',
      { name: 'Move Water the plants to tomorrow' }))
    await waitFor(() => expect(pageRows()).toEqual([]))

    // Back where it was rather than left hidden from a day it is still on.
    await act(async () => { fail(new Error('nope')) })
    await waitFor(() => expect(pageRows()).toEqual(['Water the plants']))
  })

  it('takes a row off the plan without moving it anywhere', async () => {
    m.openDay.mockResolvedValue(plan([entry({ entry_id: 'a', title: 'Water the plants' })]))
    const user = setup()
    await screen.findByText('Water the plants')
    const dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    await user.click(within(dialog).getByRole('button',
      { name: 'Take Water the plants off the plan' }))
    await waitFor(() => expect(m.patchDayEntry).toHaveBeenCalledWith(
      today(), 'a', { dropped: true }))
    expect(m.rollDayEntry).not.toHaveBeenCalled()
  })

  it('offers a habit no way to be moved, and still a way to be declined', async () => {
    // Tomorrow gets its own occurrence from the rule, so moving one would
    // either duplicate it or fabricate one on a day the rule does not schedule
    // — which is what `roll_entry` refuses by name. "I did not do this today"
    // is still a real answer.
    m.openDay.mockResolvedValue(plan([occurrence({ entry_id: 'h1', title: 'Read' })]))
    const user = setup()
    await screen.findByText('Read')
    const dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    expect(within(dialog).queryByRole('button', { name: 'Move Read to tomorrow' }))
      .not.toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Take Read off the plan' }))
      .toBeInTheDocument()
  })

  it('moves everything at once, and offers that only when there is more than one', async () => {
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'a', title: 'One' }),
      entry({ entry_id: 'b', title: 'Two' }),
      // A habit is not movable, so it is neither in the count nor in the sweep.
      occurrence({ entry_id: 'h1', title: 'Read' }),
    ]))
    const user = setup()
    await screen.findByText('One')
    const dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    await user.click(within(dialog).getByRole('button', { name: 'Move all 2 to tomorrow' }))
    await waitFor(() => expect(m.rollDayEntry).toHaveBeenCalledTimes(2))
    expect(m.rollDayEntry).toHaveBeenCalledWith(today(), 'a', inDays(1))
    expect(m.rollDayEntry).toHaveBeenCalledWith(today(), 'b', inDays(1))
    expect(m.rollDayEntry).not.toHaveBeenCalledWith(today(), 'h1', inDays(1))
  })

  it('does not offer a sweep for a single leftover', async () => {
    // The row's own button already says it, and a "move all 1" is a second
    // control for one click.
    m.openDay.mockResolvedValue(plan([entry({ entry_id: 'a', title: 'One' })]))
    const user = setup()
    await screen.findByText('One')
    const dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    expect(within(dialog).queryByRole('button', { name: /Move all/ })).not.toBeInTheDocument()
  })

  it('will not offer a day the server would refuse', async () => {
    // The rule is enforced server-side regardless — `roll_entry` will not move
    // work backwards — so this is only about the picker not inviting it.
    m.openDay.mockResolvedValue(plan([entry({ entry_id: 'a', title: 'One' })]))
    const user = setup()
    await screen.findByText('One')
    const dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    const picker = within(dialog).getByLabelText('Move One to a day')
    expect(picker).toHaveAttribute('min', inDays(1))
    expect(picker).toHaveAttribute('max', inDays(14))
  })

  it('sends a row to a day that was named', async () => {
    m.openDay.mockResolvedValue(plan([entry({ entry_id: 'a', title: 'One' })]))
    const user = setup()
    await screen.findByText('One')
    const dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    fireEvent.change(within(dialog).getByLabelText('Move One to a day'),
      { target: { value: inDays(4) } })
    await waitFor(() => expect(m.rollDayEntry).toHaveBeenCalledWith(today(), 'a', inDays(4)))
  })

  it('writes the reflection on blur, trimmed', async () => {
    // Prose, and a PATCH per keystroke would be a write storm for a field
    // nobody is racing on.
    m.patchDay.mockImplementation(async (d, body) =>
      plan([], d, { reflection: body.reflection || null }))
    const user = setup()
    const dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    const box = within(dialog).getByLabelText('A note about today')
    await user.type(box, '  Slow start, good afternoon.  ')
    expect(m.patchDay).not.toHaveBeenCalled()
    await user.tab()
    await waitFor(() => expect(m.patchDay).toHaveBeenCalledWith(
      today(), { reflection: 'Slow start, good afternoon.' }))
  })

  it('sends an emptied reflection rather than skipping it as falsy', async () => {
    // "" CLEARS, which is `set_day_ritual`'s rule and the reason "nothing
    // written" has one representation. Skipping the empty string as falsy would
    // make a reflection unremovable.
    m.openDay.mockResolvedValue(plan([], today(), { reflection: 'It was fine.' }))
    m.patchDay.mockImplementation(async (d, body) =>
      plan([], d, { reflection: body.reflection || null }))
    const user = setup()
    const dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))

    await user.clear(within(dialog).getByLabelText('A note about today'))
    await user.tab()
    await waitFor(() => expect(m.patchDay).toHaveBeenCalledWith(today(), { reflection: '' }))
  })

  it('says nothing to the server when the reflection was not touched', async () => {
    m.openDay.mockResolvedValue(plan([], today(), { reflection: 'It was fine.' }))
    const user = setup()
    const dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(within(dialog).getByLabelText('A note about today'))
    await user.tab()
    expect(m.patchDay).not.toHaveBeenCalled()
  })

  it('stops offering a task it has just sent to another day', async () => {
    // FOUND BY DRIVING THE FLOW. "Decided against" and "happening on Thursday"
    // are different answers: the first leaves the task undecided-about and it is
    // right to offer it back, the second already has a row on another day. A
    // suggestion list that offered it under "Due today" would contradict the
    // answer given ten seconds earlier in the shutdown.
    m.tasks.mockResolvedValue([task({ uid: 'u1', summary: 'Send the Q3 invoice', due: today() })])
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'a', kind: 'task', list: 'l1', uid: 'u1', title: null }),
    ]))
    // The route echoes the SOURCE row, stamped — so the reply still names the
    // task. The shared default cannot know which row it was asked about.
    m.rollDayEntry.mockImplementation(async (_d, id, to) => entry({
      entry_id: id, kind: 'task', list: 'l1', uid: 'u1', title: null, rolled_to: to,
    }))
    const user = setup()
    await screen.findByText('Send the Q3 invoice')
    const dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(within(dialog).getByRole('button',
      { name: 'Move Send the Q3 invoice to tomorrow' }))

    await waitFor(() => expect(pageRows()).toEqual([]))
    // Off the day, and NOT back in the list of things to put on it.
    expect(document.querySelector('.today-sug')).toBeNull()
  })

  it('files a moved row under its own heading, and says where it went', async () => {
    // "Happening on Thursday" and "not happening" are DIFFERENT ANSWERS, and
    // `rolled_to` exists to keep them apart: it records the decision AND its
    // destination. Filing a moved row under "Chosen" reports it as still on the
    // day; filing it under "Dropped" reports it abandoned. Both are wrong.
    m.day.mockImplementation(async (d) => plan([
      entry({ entry_id: 'a', day: d, title: 'Went to Thursday', rolled_to: inDays(4) }),
      entry({ entry_id: 'b', day: d, title: 'Declined', dropped_at: `${d}T10:00:00.000Z` }),
      entry({ entry_id: 'c', day: d, title: 'Stayed put' }),
    ], d))
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Previous day' }))
    await screen.findByText('Stayed put')

    const moved = within(screen.getByRole('list', { name: 'Moved on' }))
    expect(moved.getByText('Went to Thursday')).toBeInTheDocument()
    // WHERE it went, in place of when it was wanted by.
    expect(moved.getByText(/→/)).toBeInTheDocument()
    expect(within(screen.getByRole('list', { name: 'Dropped' }))
      .getByText('Declined')).toBeInTheDocument()
    expect(within(screen.getByRole('list', { name: 'Chosen' }))
      .getByText('Stayed put')).toBeInTheDocument()
  })

  it('hands out no controls on a row that has been moved', async () => {
    // The same call the Dropped group makes, reached from the other direction:
    // the work is on Thursday now and Thursday's row is the one to tick. A
    // checkbox here would write today's record for work today is not doing.
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'a', title: 'Went to Thursday', rolled_to: inDays(4) }),
    ]))
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Review' }))
    const row = await screen.findByText('Went to Thursday')
    const li = row.closest('li')!
    expect(li.querySelector('input[type="checkbox"]')).toBeNull()
    expect(within(li as HTMLElement)
      .queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
  })

  it('reads the reflection back on the look-back', async () => {
    // The step that writes it PROMISES "you will see it whenever you look back
    // at today", and until the look-back rendered it that promise was false:
    // the text was stored, prefilled into the box that wrote it, and shown
    // nowhere else. A field nothing reads is a field nobody fills in twice.
    m.day.mockImplementation(async (d) => plan([entry({ day: d, title: 'Yesterday' })], d, {
      reflection: 'Slow start. The invoice went out, which was the one that mattered.',
    }))
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Previous day' }))
    await screen.findByText('Yesterday')
    expect(screen.getByText(/The invoice went out/)).toBeInTheDocument()
  })

  it('shows no heading for a day nothing was written about', async () => {
    m.day.mockImplementation(async (d) => plan([entry({ day: d, title: 'Yesterday' })], d))
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Previous day' }))
    await screen.findByText('Yesterday')
    expect(screen.queryByText('How it went')).not.toBeInTheDocument()
  })

  it('closes the day, and says so when you come back', async () => {
    m.patchDay.mockImplementation(async (d) =>
      plan([], d, { shutdown_at: `${d}T18:04:00.000Z` }))
    const user = setup()
    const dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(within(dialog).getByRole('button', { name: 'Shut down' }))

    await waitFor(() => expect(m.patchDay).toHaveBeenCalledWith(today(), { shutdown: true }))
    // The ritual gets out of the way once it is walked.
    await waitFor(() => expect(
      screen.queryByRole('dialog', { name: 'Shut down the day' })).not.toBeInTheDocument())

    // And it is RE-ENTERABLE — an evening thought belongs in the same
    // reflection — so it reports the stamp rather than refusing.
    const again = await open(user)
    expect(within(again).getByText(/You shut today down at/)).toBeInTheDocument()
    await user.click(within(again).getByRole('button', { name: 'Next' }))
    await user.click(within(again).getByRole('button', { name: 'Next' }))
    // And the last button says so too, rather than offering to do it twice.
    expect(within(again).getByRole('button', { name: 'Done' })).toBeInTheDocument()
  })
})

// ── how full the day is ─────────────────────────────────────────────────────

describe('<TodayView> how full the day is', () => {
  const withCapacity = (entries: DayEntry[], capacity: number | null) =>
    plan(entries, today(), { capacity, capacity_minutes: capacity })

  it('says nothing at all when no capacity has ever been given', async () => {
    // THE CASE THAT MATTERS MOST. An account that has not stated a capacity
    // gets no strip, no total and no warning — because there is no honest
    // number to put in one, and inventing an eight-hour day for them is the one
    // thing this feature must not do.
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants', estimate_minutes: 30 })]))
    setup()
    await screen.findByText('Water the plants')
    expect(document.querySelector('.today-load')).toBeNull()
  })

  it('totals only the rows that carry an estimate', async () => {
    // An unestimated row contributes NOTHING rather than an assumed default.
    // That leaves the total honestly low, which is the right direction — a
    // guessed number is one nobody can act on — and the count beside it says
    // how much of the day the figure is silent about.
    m.openDay.mockResolvedValue(withCapacity([
      entry({ entry_id: 'a', title: 'One', estimate_minutes: 45, position: 1 }),
      entry({ entry_id: 'b', title: 'Two', estimate_minutes: 75, position: 2 }),
      entry({ entry_id: 'c', title: 'Three', position: 3 }),
    ], 300))
    setup()
    await screen.findByText('One')

    expect(document.querySelector('.today-load-fig')!.textContent).toBe('2h of 5h')
    expect(document.querySelector('.today-load-rest')!.textContent)
      .toMatch(/1 not estimated/)
  })

  it('does not count a row that was dropped', async () => {
    // Declining something is how you get back under, so a total that kept
    // counting it would make the one control that helps useless.
    m.openDay.mockResolvedValue(withCapacity([
      entry({ entry_id: 'a', title: 'One', estimate_minutes: 60, position: 1 }),
      entry({ entry_id: 'b', title: 'Gone', estimate_minutes: 600, position: 2,
        dropped_at: `${today()}T10:00:00.000Z` }),
    ], 300))
    setup()
    await screen.findByText('One')
    expect(document.querySelector('.today-load-fig')!.textContent).toBe('1h of 5h')
  })

  it('warns above the capacity and not at it', async () => {
    // Exactly at capacity is a full day, not an overcommitted one — the
    // boundary is worth pinning because off-by-one here means the tab tells
    // somebody off for planning precisely what they said they would do.
    m.openDay.mockResolvedValue(withCapacity(
      [entry({ title: 'Exactly', estimate_minutes: 300 })], 300))
    setup()
    await screen.findByText('Exactly')
    expect(document.querySelector('.today-load.over')).toBeNull()
    // And the figure still reports the day as full, so "not over" is not being
    // achieved by failing to count it.
    expect(document.querySelector('.today-load-fig')!.textContent).toBe('5h of 5h')
  })

  it('warns in words as well as in colour', async () => {
    // The colour is the half that does not survive a screen reader, a greyscale
    // screenshot or a custom theme, so it is never the only carrier.
    m.openDay.mockResolvedValue(withCapacity(
      [entry({ title: 'Too much', estimate_minutes: 480 })], 300))
    setup()
    await screen.findByText('Too much')

    expect(document.querySelector('.today-load.over')).not.toBeNull()
    expect(await screen.findByRole('status')).toHaveTextContent(
      /3h more than you said you would work/)
  })

  it('counts the calendar beside the plan, never inside it', async () => {
    // An event is committed time, but whether a given one is WORK is a
    // judgement the app does not get to make — lunch and the dentist are on the
    // same calendar as the standup. So the collision is shown and the
    // arithmetic is left alone.
    m.calendars.mockResolvedValue([cal])
    m.events.mockResolvedValue([calEvent()])
    m.openDay.mockResolvedValue(withCapacity(
      [entry({ title: 'One', estimate_minutes: 60 })], 300))
    setup()
    await screen.findByText('One')

    await waitFor(() => expect(
      document.querySelector('.today-load-cal')?.textContent).toMatch(/1h 30m on the calendar/))
    // Unchanged by the meeting: it is context, not a deduction.
    expect(document.querySelector('.today-load-fig')!.textContent).toBe('1h of 5h')
  })

  it('ignores an all-day event, which is a label rather than eight hours', async () => {
    m.calendars.mockResolvedValue([cal])
    m.events.mockResolvedValue([calEvent({
      summary: "Anna's birthday", all_day: true,
      start: today(), start_is_date: true, end: today(), end_is_date: true,
    })])
    m.openDay.mockResolvedValue(withCapacity(
      [entry({ title: 'One', estimate_minutes: 60 })], 300))
    setup()
    await screen.findByText('One')
    expect(document.querySelector('.today-load-cal')).toBeNull()
  })
})

// ── estimating a row ────────────────────────────────────────────────────────

describe('<TodayView> estimating a row', () => {
  const estimateButton = (name: RegExp) => screen.getByRole('button', { name })

  it('offers an estimate on every row, and says nothing until asked', async () => {
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    setup()
    await screen.findByText('Water the plants')

    // `est` rather than a dash or a zero. A dash is a value; this is an
    // invitation — and "takes no time" versus "nobody has said" is the
    // distinction the running total is built on.
    expect(estimateButton(/^Estimate Water the plants$/).textContent).toBe('est')
  })

  it('takes a number and shows it as a duration', async () => {
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    m.patchDayEntry.mockImplementation(async (_d, id, body) =>
      entry({ entry_id: id, title: 'Water the plants', ...body as object }))
    const user = setup()
    await screen.findByText('Water the plants')

    await user.click(estimateButton(/^Estimate Water the plants$/))
    await user.type(screen.getByLabelText('Minutes for Water the plants'), '90{Enter}')

    await waitFor(() => expect(m.patchDayEntry).toHaveBeenCalledWith(
      today(), 'e1', { estimate_minutes: 90 }))
    // Read back through fmtDuration, so the row says what a person would say.
    await waitFor(() => expect(
      screen.getByRole('button', { name: /estimated at 1h 30m/ })).toBeInTheDocument())
  })

  it('keeps a deliberate zero', async () => {
    // 0 is a real answer — "not worth counting" — and must not be swallowed as
    // falsy anywhere between the input and the wire. It is the whole reason the
    // clear needed a sentinel of its own.
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    const user = setup()
    await screen.findByText('Water the plants')
    await user.click(estimateButton(/^Estimate Water the plants$/))
    await user.type(screen.getByLabelText('Minutes for Water the plants'), '0{Enter}')

    await waitFor(() => expect(m.patchDayEntry).toHaveBeenCalledWith(
      today(), 'e1', { estimate_minutes: 0 }))
  })

  it('clears with an empty field, and spells that -1 on the wire', async () => {
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants', estimate_minutes: 30 })]))
    const user = setup()
    await screen.findByText('Water the plants')

    await user.click(screen.getByRole('button', { name: /estimated at 30m/ }))
    await user.clear(screen.getByLabelText('Minutes for Water the plants'))
    await user.keyboard('{Enter}')

    // An int has no spare falsy value to mean "unset", so the sentinel is
    // explicit — and it is translated at the one call site rather than leaking
    // into the control that collects the number.
    await waitFor(() => expect(m.patchDayEntry).toHaveBeenCalledWith(
      today(), 'e1', { estimate_minutes: -1 }))
  })

  it('holds the estimate to a day, whatever is typed', async () => {
    // Bounded in JS as well as by the input's own max, because `max` on a number
    // input does not stop a typed value — the same belt-and-braces
    // `SchedulingView` applies to every duration it takes.
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    const user = setup()
    await screen.findByText('Water the plants')
    await user.click(estimateButton(/^Estimate Water the plants$/))
    await user.type(screen.getByLabelText('Minutes for Water the plants'), '99999{Enter}')

    await waitFor(() => expect(m.patchDayEntry).toHaveBeenCalledWith(
      today(), 'e1', { estimate_minutes: 1440 }))
  })

  it('abandons the edit on Escape without closing anything above it', async () => {
    // The stopPropagation is load-bearing rather than tidy: `useEscape` is bound
    // to the window, so without it abandoning an estimate would also close the
    // habits sheet — or any other dialog standing over this row.
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    const user = setup()
    await screen.findByText('Water the plants')
    await user.click(screen.getByRole('button', { name: 'Habits' }))
    await screen.findByRole('dialog', { name: 'Habits' })

    await user.click(estimateButton(/^Estimate Water the plants$/))
    await user.type(screen.getByLabelText('Minutes for Water the plants'), '45')
    await user.keyboard('{Escape}')

    expect(m.patchDayEntry).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'Habits' })).toBeInTheDocument()
  })

  it('puts the old estimate back when the write does not land', async () => {
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants', estimate_minutes: 30 })]))
    m.patchDayEntry.mockRejectedValue(new Error('nope'))
    const user = setup()
    await screen.findByText('Water the plants')

    await user.click(screen.getByRole('button', { name: /estimated at 30m/ }))
    await user.clear(screen.getByLabelText('Minutes for Water the plants'))
    await user.type(screen.getByLabelText('Minutes for Water the plants'), '90{Enter}')

    await waitFor(() => expect(m.patchDayEntry).toHaveBeenCalled())
    await waitFor(() => expect(
      screen.getByRole('button', { name: /estimated at 30m/ })).toBeInTheDocument())
  })

  it('shows a finished day what was estimated and offers no way to change it', async () => {
    m.day.mockImplementation(async (d) => plan([
      entry({ day: d, title: 'Yesterday', estimate_minutes: 45 }),
      entry({ entry_id: 'e2', day: d, title: 'Unestimated', position: 2 }),
    ], d))
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Previous day' }))
    await screen.findByText('Yesterday')

    expect(screen.getByText('45m')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Estimate / })).not.toBeInTheDocument()
    // And NOTHING on the row nobody estimated: a dim "add one" on a day that has
    // already happened is an invitation to rewrite the record.
    expect(screen.queryByText('est')).not.toBeInTheDocument()
  })
})

// ── arranging the day ───────────────────────────────────────────────────────

describe('<TodayView> arranging the day', () => {
  /** Three rows at positions 1, 2, 3 — A, B, C top to bottom. */
  const abc = () => plan([
    entry({ entry_id: 'a', title: 'Alpha', position: 1 }),
    entry({ entry_id: 'b', title: 'Bravo', position: 2 }),
    entry({ entry_id: 'c', title: 'Charlie', position: 3 }),
  ])

  /**
   * Drag the row titled `from` onto the row titled `to`.
   *
   * ONE `dataTransfer` for the whole gesture, as a real drag has — and it has to
   * be supplied at all because jsdom builds a DragEvent WITHOUT one, so
   * `onDragStart`'s `e.dataTransfer.effectAllowed = 'move'` throws on undefined.
   * This is the same stand-in every other drag suite in this repo passes
   * (TasksView, both stage4 backlogs), and this helper was the one
   * `fireEvent.dragStart` in the codebase that omitted it.
   *
   * The failure it caused is worth keeping written down, because nothing about
   * it looked like a failure: the throw lands AFTER `onDragRow` has already run,
   * so every assertion below still held and all 1057 tests still passed — while
   * vitest exited 1 on five unhandled errors and the `effectAllowed` line was
   * never once executed by any test. `TasksView.test.tsx` says the same thing
   * over its own stub; this is the second time the lesson has been paid for.
   */
  const dragOnto = (from: string, to: string) => {
    const row = (t: string) =>
      dayRows().find((r) => r.querySelector('.today-title')?.textContent === t)!
    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }
    // `mousedown` first, on the title, because that is the order a browser
    // produces and the row's guard reads it — see the estimate-input test.
    fireEvent.mouseDown(row(from).querySelector('.today-title')!)
    fireEvent.dragStart(row(from), { dataTransfer })
    fireEvent.dragOver(row(to), { dataTransfer })
    fireEvent.drop(row(to), { dataTransfer })
    return dataTransfer
  }

  it('puts a payload on the transfer, like every other drag in this app', async () => {
    // Consistency rather than a browser bug: the "Firefox will not start an
    // empty drag" reason the other four sites give was true of old Firefox and
    // is not of any current one. A gesture carrying nothing is still one no
    // external drop target can read, and this was the only drag source here
    // that carried nothing.
    m.openDay.mockResolvedValue(abc())
    setup()
    await screen.findByText('Alpha')

    const dt = dragOnto('Alpha', 'Bravo')
    expect(dt.setData).toHaveBeenCalledWith('text/plain', expect.any(String))
  })

  it('leaves a press inside the estimate input to the input', async () => {
    // `draggable` is on the ROW and the row contains an editable control, so
    // without a guard, selecting the text of an estimate reorders the day.
    //
    // THE EVENTS HERE ARE FIRED IN THE ORDER AND AT THE TARGETS A BROWSER USES,
    // and that is the whole point of this test rather than an incidental
    // detail. `mousedown` lands on the deepest node — the input — and
    // `dragstart` is fired at the drag SOURCE NODE, the row. Measured in
    // Chromium, not assumed.
    //
    // The first version of this test fired `dragstart` AT THE INPUT, which no
    // browser does, and so it passed against a guard that was inert everywhere
    // it mattered. Firing it at the row is what makes the assertion mean
    // something: with the flag removed, the drag starts and the row moves.
    m.openDay.mockResolvedValue(abc())
    const user = setup()
    await screen.findByText('Alpha')

    // Open the estimate cell on Alpha, so there is a real input inside the row.
    await user.click(screen.getByRole('button', { name: 'Estimate Alpha' }))
    const row = dayRows()[0]
    const input = row.querySelector('input[type="number"]')!
    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }

    fireEvent.mouseDown(input)
    fireEvent.dragStart(row, { dataTransfer })
    fireEvent.dragOver(dayRows()[1], { dataTransfer })
    fireEvent.drop(dayRows()[1], { dataTransfer })

    // Nothing was picked up, so nothing moved and nothing was written.
    expect(dataTransfer.setData).not.toHaveBeenCalled()
    expect(dataTransfer.effectAllowed).toBe('')
    expect(m.patchDayEntry).not.toHaveBeenCalled()
    expect(rowTitles()).toEqual(['Alpha', 'Bravo', 'Charlie'])
  })

  it('still starts a drag when the row is grabbed anywhere else', async () => {
    // The other half, and the one that stops the guard being a way to disable
    // arranging altogether: a press on the title is not a press on a control.
    m.openDay.mockResolvedValue(abc())
    setup()
    await screen.findByText('Alpha')

    const row = dayRows()[0]
    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }
    fireEvent.mouseDown(row.querySelector('.today-title')!)
    fireEvent.dragStart(row, { dataTransfer })
    expect(dataTransfer.effectAllowed).toBe('move')
  })

  it('still starts a drag when the row is grabbed by a button', async () => {
    // The guard is TEXT FIELDS ONLY, and this says so. It once matched `button`
    // too, which is a wider net than the problem: the failure is that dragging
    // to SELECT TEXT reorders instead, and a button has no drag semantics of
    // its own — so a press-drag beginning on the checkbox or the estimate's
    // collapsed cell may as well take the row with it. Guarding those would
    // only take grab area away.
    m.openDay.mockResolvedValue(abc())
    setup()
    await screen.findByText('Alpha')

    const row = dayRows()[0]
    for (const control of [
      row.querySelector('.check')!,
      screen.getByRole('button', { name: 'Estimate Alpha' }),
    ]) {
      const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }
      fireEvent.mouseDown(control)
      fireEvent.dragStart(row, { dataTransfer })
      expect(dataTransfer.effectAllowed).toBe('move')
    }
  })

  it('tells the browser the gesture is a MOVE, not a copy', async () => {
    // The one line of `onDragStart` that no test reached: it threw on an absent
    // `dataTransfer` every time, and the throw was invisible because it came
    // after the state had already been set. Without `effectAllowed` the browser
    // paints a copy cursor over a gesture that moves a row.
    m.openDay.mockResolvedValue(abc())
    setup()
    await screen.findByText('Alpha')

    expect(dragOnto('Alpha', 'Bravo').effectAllowed).toBe('move')
  })

  it('drops a row between its new neighbours with ONE write', async () => {
    // `day_plan.position` is a REAL and the server orders on it, so a move is a
    // midpoint and nothing else has to be renumbered. A whole-list rewrite would
    // be N writes for a gesture that moved one row.
    m.openDay.mockResolvedValue(abc())
    setup()
    await screen.findByText('Alpha')

    // Alpha onto Bravo: dragging DOWN lands it after the target, so between
    // Bravo (2) and Charlie (3).
    dragOnto('Alpha', 'Bravo')
    await waitFor(() => expect(m.patchDayEntry).toHaveBeenCalledWith(
      today(), 'a', { position: 2.5 }))
    expect(m.patchDayEntry).toHaveBeenCalledTimes(1)
  })

  it('lands a row before the target when it is dragged upward', async () => {
    // The other direction, and the reason the arithmetic is worth a test of its
    // own: removing the dragged row shifts every later index by one, so an
    // off-by-one here silently moves rows to the wrong side of their target.
    m.openDay.mockResolvedValue(abc())
    setup()
    await screen.findByText('Alpha')

    // Charlie onto Bravo: dragging UP lands it before the target, so between
    // Alpha (1) and Bravo (2).
    dragOnto('Charlie', 'Bravo')
    await waitFor(() => expect(m.patchDayEntry).toHaveBeenCalledWith(
      today(), 'c', { position: 1.5 }))
  })

  it('takes a row past the ends of the list', async () => {
    m.openDay.mockResolvedValue(abc())
    setup()
    await screen.findByText('Alpha')

    // Charlie to the top: before Alpha (1), so below it.
    dragOnto('Charlie', 'Alpha')
    await waitFor(() => expect(m.patchDayEntry).toHaveBeenCalledWith(
      today(), 'c', { position: 0 }))
  })

  it('re-sorts on the drop rather than on the reply', async () => {
    m.openDay.mockResolvedValue(abc())
    m.patchDayEntry.mockImplementation(async (_d, id, body) =>
      entry({ entry_id: id, ...body as object }))
    setup()
    await screen.findByText('Alpha')
    expect(rowTitles()).toEqual(['Alpha', 'Bravo', 'Charlie'])

    dragOnto('Alpha', 'Charlie')
    await waitFor(() => expect(rowTitles()).toEqual(['Bravo', 'Charlie', 'Alpha']))
  })

  it('puts the row back exactly where it was when the move does not land', async () => {
    m.openDay.mockResolvedValue(abc())
    m.patchDayEntry.mockRejectedValue(new Error('nope'))
    setup()
    await screen.findByText('Alpha')

    dragOnto('Alpha', 'Charlie')
    await waitFor(() => expect(m.patchDayEntry).toHaveBeenCalled())
    await waitFor(() => expect(rowTitles()).toEqual(['Alpha', 'Bravo', 'Charlie']))
  })

  it('never lets a habit be dragged', async () => {
    // An occurrence's position is minted fresh by its rule every morning, so an
    // order dragged into the spine would be gone tomorrow — and habits paint in
    // their own group, so it would not even show where it was made.
    m.openDay.mockResolvedValue(plan([
      occurrence({ entry_id: 'h', title: 'Read', position: 1 }),
      entry({ entry_id: 'a', title: 'Alpha', position: 2 }),
      entry({ entry_id: 'b', title: 'Bravo', position: 3 }),
    ]))
    setup()
    await screen.findByText('Alpha')

    const habitRow = screen.getByRole('list', { name: 'Habits' })
      .querySelector('.today-row')!
    expect(habitRow.getAttribute('draggable')).not.toBe('true')
    // The ordinary rows beside it still are.
    expect(dayRows()[0].getAttribute('draggable')).toBe('true')
  })

  it('refuses to arrange while an add is still in flight', async () => {
    // An optimistic row has no position until the server answers, and
    // `orderEntries` sorts an unpositioned row to the END — so a midpoint taken
    // now would be measured against a neighbour that is about to move.
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'a', title: 'Alpha', position: 1 }),
      entry({ entry_id: 'b', title: 'Bravo', position: null }),
    ]))
    setup()
    await screen.findByText('Alpha')

    expect(dayRows().every((r) => r.getAttribute('draggable') !== 'true')).toBe(true)
  })

  it('offers no arranging on a day with one row, or none', async () => {
    m.openDay.mockResolvedValue(plan([entry({ entry_id: 'a', title: 'Alpha', position: 1 })]))
    setup()
    await screen.findByText('Alpha')
    expect(dayRows()[0].getAttribute('draggable')).not.toBe('true')
  })

  it('hands out no arranging on a finished day', async () => {
    m.day.mockImplementation(async (d) => plan([
      entry({ entry_id: 'a', day: d, title: 'Alpha', position: 1 }),
      entry({ entry_id: 'b', day: d, title: 'Bravo', position: 2 }),
    ], d))
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Previous day' }))
    await screen.findByText('Alpha')

    expect(dayRows().every((r) => r.getAttribute('draggable') !== 'true')).toBe(true)
  })

  it('hands out no arranging while today is being reviewed', async () => {
    // A review is a record of the day, and a record is not a thing you shuffle.
    m.openDay.mockResolvedValue(abc())
    const user = setup()
    await screen.findByText('Alpha')
    expect(dayRows()[0].getAttribute('draggable')).toBe('true')

    await user.click(screen.getByRole('button', { name: 'Review' }))
    await waitFor(() =>
      expect(dayRows().every((r) => r.getAttribute('draggable') !== 'true')).toBe(true))
  })
})

// ── reviewing today ─────────────────────────────────────────────────────────

describe('<TodayView> reviewing today', () => {
  /** A day with one row from each source, plus a dropped one — the same shape
   *  the past-day suite builds, so the two screens are asserted to bucket a day
   *  identically. */
  const mixed = () => plan([
    entry({ entry_id: 'e-user', source: 'user', title: 'Chosen thing', position: 1 }),
    entry({ entry_id: 'e-carry', source: 'carried', title: 'Carried thing', position: 2 }),
    entry({ entry_id: 'e-auto', source: 'auto', title: 'Derived thing', position: 3 }),
    occurrence({ entry_id: 'e-hab', title: 'Read', position: 4 }),
    entry({ entry_id: 'e-drop', source: 'user', title: 'Bailed on this',
      dropped_at: '2026-08-24T12:00:00.000Z', position: 5 }),
  ])

  it('reviews today without opening anything', async () => {
    // THE LOAD-BEARING TEST OF THIS FEATURE. `api.openDay` is the only call that
    // can CREATE a plan, and the rule this whole file is built around is that it
    // is called for today and for nothing else. A review is a render-level
    // switch over data already in hand, so going in and back out must not move
    // the open count and must never reach for the pure read either.
    m.openDay.mockResolvedValue(mixed())
    const user = setup()
    await screen.findByText('Chosen thing')
    expect(m.openDay).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: 'Review' }))
    await screen.findByText('Bailed on this')
    await user.click(screen.getByRole('button', { name: 'Plan' }))
    await screen.findByText('Chosen thing')

    expect(m.openDay).toHaveBeenCalledTimes(1)
    expect(m.day).not.toHaveBeenCalled()
  })

  it('splits today by where each row came from', async () => {
    // The same five headings, from the same buckets, as a finished day — this
    // is `LookBack` reused verbatim rather than a second description of a day.
    m.openDay.mockResolvedValue(mixed())
    const user = setup()
    await screen.findByText('Chosen thing')
    await user.click(screen.getByRole('button', { name: 'Review' }))

    for (const h of ['Chosen', 'Carried over', 'Derived', 'Habits', 'Dropped']) {
      expect(await screen.findByRole('list', { name: h })).toBeInTheDocument()
    }
    // The dropped row is only ever visible here: the day's own lists filter it.
    expect(screen.getByText('Bailed on this')).toBeInTheDocument()
  })

  it('shows what was finished today and never planned', async () => {
    m.tasks.mockResolvedValue([task({
      uid: 'off', summary: 'Did this anyway', completed: true,
      completed_at: `${today()}T14:30:00`,
    })])
    m.openDay.mockResolvedValue(plan([entry({ title: 'On the plan' })]))
    const user = setup()
    await screen.findByText('On the plan')
    await user.click(screen.getByRole('button', { name: 'Review' }))

    expect(await screen.findByRole('list', { name: 'Done off-plan' })).toBeInTheDocument()
    expect(screen.getByText('Did this anyway')).toBeInTheDocument()
  })

  it('keeps today workable while it is being reviewed', async () => {
    // The difference from a finished day, and the reason `readOnly` stays keyed
    // on `isToday` and never on the mode: today is still running. Its rows tick,
    // and a note still ticks through the entry PATCH.
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    const user = setup()
    await screen.findByText('Water the plants')
    await user.click(screen.getByRole('button', { name: 'Review' }))

    const check = await screen.findByRole('button', { name: /^Check Water the plants/ })
    await user.click(check)
    await waitFor(() => expect(m.patchDayEntry).toHaveBeenCalledWith(
      today(), 'e1', { done: true }))
  })

  it('still takes a line while today is being reviewed', async () => {
    // Gated on `isToday`, not on the mode. "Note down the thing I actually did"
    // is the commonest reason to be on this screen in the evening, and every
    // other control on the row is still live.
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    const user = setup()
    await screen.findByText('Water the plants')
    await user.click(screen.getByRole('button', { name: 'Review' }))

    await user.type(await screen.findByLabelText('Add to today'), 'rang the bank{Enter}')
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalledWith(
      today(), expect.objectContaining({ kind: 'note', title: 'rang the bank' })))
  })

  it('does not offer more work while reviewing', async () => {
    m.tasks.mockResolvedValue([task({ due: today(), due_is_date: true })])
    const user = setup()
    await screen.findByRole('button', { name: /Add Ship it to today/ })

    await user.click(screen.getByRole('button', { name: 'Review' }))
    await waitFor(() => expect(
      screen.queryByRole('button', { name: /Add Ship it to today/ })).not.toBeInTheDocument())
    expect(screen.queryByText('Due today')).not.toBeInTheDocument()
  })

  it('counts the day the other way up while reviewing', async () => {
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'a', title: 'Done one', done_at: `${today()}T09:00:00`, position: 1 }),
      entry({ entry_id: 'b', title: 'Still open', position: 2 }),
    ]))
    const user = setup()
    await screen.findByText('Still open')
    expect(screen.getByText(/1 open · 2 on the day/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Review' }))
    expect(await screen.findByText(/1 done · 2 on the day/)).toBeInTheDocument()
  })

  it('keeps calling today Today', async () => {
    // The heading is the one thing on this surface that must never lie about
    // which day is on screen. Reviewing today is still today; "Look back" is
    // reserved for a day that has actually finished.
    const user = setup()
    await screen.findByRole('button', { name: 'Review' })
    await user.click(screen.getByRole('button', { name: 'Review' }))

    expect(document.querySelector('.content-title')?.textContent).toBe('Today')
  })

  it('says so in the present tense when today has nothing on it yet', async () => {
    const user = setup()
    await screen.findByRole('button', { name: 'Review' })
    await user.click(screen.getByRole('button', { name: 'Review' }))

    expect(await screen.findByText(/Nothing on today yet, and nothing finished so far/))
      .toBeInTheDocument()
    expect(screen.queryByText(/Nothing was planned on this day/)).not.toBeInTheDocument()
  })

  it('treats a row dropped today as the record it is', async () => {
    // Before today could be reviewed, "past day" and "dropped" were the same
    // set, so `!isToday` covered both. They came apart here: the Dropped group
    // on a LIVE day would otherwise hand out a checkbox for ticking something
    // the owner declined, and a ✕ for dropping what is already dropped.
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'live', title: 'Still going', position: 1 }),
      entry({ entry_id: 'gone', title: 'Bailed on this', position: 2,
        dropped_at: `${today()}T12:00:00.000Z` }),
    ]))
    const user = setup()
    await screen.findByText('Still going')
    await user.click(screen.getByRole('button', { name: 'Review' }))
    await screen.findByText('Bailed on this')

    expect(screen.queryByRole('button', { name: /Bailed on this/ })).not.toBeInTheDocument()
    // The row beside it is still live, so this is the dropped-ness doing it and
    // not the mode.
    expect(screen.getByRole('button', { name: /^Check Still going/ })).toBeInTheDocument()
  })

  it('offers no review toggle on a finished day, because the day is one', async () => {
    m.day.mockImplementation(async (d) => plan([entry({ day: d, title: 'Yesterday' })], d))
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Previous day' }))
    await screen.findByText('Yesterday')

    expect(screen.queryByRole('button', { name: 'Review' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Plan' })).not.toBeInTheDocument()
    expect(document.querySelector('.content-title')?.textContent).toBe('Look back')
  })

  it('leaves a finished day read-only even when today was left in review', async () => {
    // `mode` survives the trip, like the habits sheet does — but `readOnly` is
    // keyed on `isToday`, so a past day is a record whichever mode today was in.
    m.day.mockImplementation(async (d) => plan([entry({ day: d, title: 'Yesterday' })], d))
    const user = setup()
    await screen.findByRole('button', { name: 'Review' })
    await user.click(screen.getByRole('button', { name: 'Review' }))
    await user.click(screen.getByRole('button', { name: 'Previous day' }))
    await screen.findByText('Yesterday')

    expect(screen.queryByLabelText('Add to today')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Check / })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Remove / })).not.toBeInTheDocument()
  })
})

// ── how much a suggestion group shows ───────────────────────────────────────

describe('<TodayView> capping the suggestions', () => {
  /** N open tasks due today, each with its own uid so they are distinct rows. */
  const dueToday = (n: number) => Array.from({ length: n }, (_, i) =>
    task({ uid: `u${i}`, summary: `Task ${i}`, due: today(), due_is_date: true }))

  it('shows the first few of a long group, and says how many it is holding', async () => {
    // Five groups each rendering everything they matched put the day itself off
    // the top of the screen on any account with a backlog. The count is in the
    // label so the bound is never a mystery.
    m.tasks.mockResolvedValue(dueToday(8))
    setup()
    await screen.findByText('Task 0')

    expect(document.querySelectorAll('.today-sug')).toHaveLength(5)
    expect(await screen.findByRole('button', { name: 'Show all 8' })).toBeInTheDocument()
    expect(screen.queryByText('Task 7')).not.toBeInTheDocument()
  })

  it('shows the rest on one press', async () => {
    m.tasks.mockResolvedValue(dueToday(8))
    const user = setup()
    await screen.findByText('Task 0')

    await user.click(screen.getByRole('button', { name: 'Show all 8' }))
    expect(document.querySelectorAll('.today-sug')).toHaveLength(8)
    expect(screen.getByText('Task 7')).toBeInTheDocument()
    // Gone once there is nothing left to show — it names a remainder, and there
    // isn't one.
    expect(screen.queryByRole('button', { name: /^Show all/ })).not.toBeInTheDocument()
  })

  it('offers no way past a group that is already whole', async () => {
    m.tasks.mockResolvedValue(dueToday(3))
    setup()
    await screen.findByText('Task 0')

    expect(document.querySelectorAll('.today-sug')).toHaveLength(3)
    expect(screen.queryByRole('button', { name: /^Show all/ })).not.toBeInTheDocument()
  })

  it('still keeps one task to one heading when a group is capped', async () => {
    // THE REASON THE CAP IS AT THE RENDER. `group()` walks every item it matched
    // into the `offered` set, and that set is what keeps the five groups
    // disjoint. Capping where the groups are BUILT would leave the sixth
    // due-today task un-offered, so it would come back under "Overdue" as a
    // second "add" button for a row already listed above — and the first press
    // makes the second a no-op the owner cannot explain.
    //
    // These eight are due EARLIER today, so every one of them is both
    // `dayKey(due) === day` and `isOverdue`.
    const t = Array.from({ length: 8 }, (_, i) => task({
      uid: `u${i}`, summary: `Task ${i}`, due: `${today()}T00:01`, due_is_date: false,
    }))
    m.tasks.mockResolvedValue(t)
    const user = setup()
    await screen.findByText('Task 0')

    expect(screen.getByText('Due today')).toBeInTheDocument()
    expect(screen.queryByText('Overdue')).not.toBeInTheDocument()
    expect(document.querySelectorAll('.today-sug')).toHaveLength(5)

    // And the three the cap withheld are still that one group's, not a second
    // group's — they appear under "Due today" and nowhere else.
    await user.click(screen.getByRole('button', { name: 'Show all 8' }))
    expect(document.querySelectorAll('.today-sug')).toHaveLength(8)
    expect(screen.queryByText('Overdue')).not.toBeInTheDocument()
  })

  it('caps each group on its own', async () => {
    // The cap is per group, not a budget shared across the panel: each heading
    // answers a different question and one of them running long must not
    // silence the next.
    m.tasks.mockResolvedValue([
      ...dueToday(7),
      ...Array.from({ length: 7 }, (_, i) => task({
        uid: `o${i}`, summary: `Late ${i}`, due: inDays(-3), due_is_date: true,
      })),
    ])
    setup()
    await screen.findByText('Task 0')

    expect(document.querySelectorAll('.today-sug')).toHaveLength(10)
    expect(screen.getAllByRole('button', { name: /^Show all 7$/ })).toHaveLength(2)
  })
})

// ── what the add box promises ───────────────────────────────────────────────

describe('<TodayView> what the add box promises', () => {
  const otherList: List = {
    id: 'l2', href: '/l2/', name: 'Errands', is_task_list: true, is_calendar: false,
    open_count: 0, task_count: 0, event_count: 0, total: 0, color: null,
  }

  it('says a plain line will become a note, and where it will live', async () => {
    // THE CASE THE OLD CHIP NEVER COVERED, and the one that needed it most: a
    // line with no date silently became a note that exists nowhere but in this
    // day and reaches no other client on the account. Nothing said so.
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'call mum')

    await waitFor(() => expect(fateChip()).not.toBeNull())
    expect(fateChip()!.textContent).toMatch(/Note/)
    expect(fateChip()!.textContent).toMatch(/this day only/)
    expect(fateChip()!.textContent).toMatch(/never leaves Smylte/)
  })

  it('says a dated line will become a task, and names the list it lands on', async () => {
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'gym at 7')

    await waitFor(() => expect(fateChip()).not.toBeNull())
    expect(fateChip()!.textContent).toMatch(/Task/)
    // The list was never named anywhere before — the box just picked one.
    expect(fateChip()!.textContent).toMatch(/Work/)
    expect(fateChip()!.textContent).toMatch(/other apps/)
  })

  it('carries the outcome in the submit button, not in a live region', async () => {
    // What a screen reader gets instead of the chip's wording, and it is better
    // placed: heard when the button is reached, an instant before it fires. A
    // live region would have re-announced on every keystroke.
    const user = setup()
    const box = screen.getByLabelText('Add to today')
    await user.type(box, 'call mum')
    expect(await screen.findByRole('button', { name: 'Add as note' })).toBeInTheDocument()

    await user.clear(box)
    await user.type(box, 'gym at 7')
    expect(await screen.findByRole('button', { name: 'Add as task' })).toBeInTheDocument()
  })

  it('ties the line to the box it describes', async () => {
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'call mum')
    await waitFor(() => expect(fateChip()).not.toBeNull())
    expect(screen.getByLabelText('Add to today'))
      .toHaveAttribute('aria-describedby', 'today-add-fate')
  })

  it('says nothing at all about an empty box', async () => {
    // The line answers "what will Enter do"; with nothing typed there is no
    // question, and a permanent caption under the field would be noise.
    setup()
    await screen.findByLabelText('Add to today')
    expect(fateChip()).toBeNull()
    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled()
  })

  it('makes a task out of a plain line, with NO due date', async () => {
    // The reachable-only-now case: "make it a task" about a line with no date
    // in it. `dueFromParse` falls back to the day being planned, which would
    // stamp a deadline of today onto a VTODO every other client then shows as
    // due — off the back of the owner asking only for it to be a task. Being on
    // today's plan is the day entry's job.
    m.createTask.mockResolvedValue(task({ uid: 'new@tasksd', summary: 'call mum' }))
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'call mum')
    await user.click(await screen.findByRole('button', { name: 'Make it a task' }))
    await user.type(screen.getByLabelText('Add to today'), '{Enter}')

    await waitFor(() => expect(m.createTask).toHaveBeenCalled())
    expect(m.createTask.mock.calls[0][1]).not.toHaveProperty('due')
    expect(m.createTask.mock.calls[0][1]).toMatchObject({ summary: 'call mum' })
  })

  it('keeps the chosen kind while the rest of the line is typed', async () => {
    // The departure from the old `declined`, which reset on every keystroke.
    // That was right for a decision about a PARSE — one more character can
    // withdraw a parse — and wrong for a decision about intent. Clearing it
    // under the owner's fingers would be a fresh instance of exactly the silent
    // surprise this change removes.
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'gym at 7')
    await user.click(await screen.findByRole('button', { name: 'Make it a note' }))
    await user.type(screen.getByLabelText('Add to today'), ' sharp')

    expect(fateChip()!.textContent).toMatch(/Note/)
    expect(screen.getByRole('button', { name: 'Add as note' })).toBeInTheDocument()
  })

  it('forgets the chosen kind when the line is abandoned', async () => {
    // Emptying the box abandons the line, and the pin was a statement about
    // that line. Typing ON is a different thing and keeps it — see the test
    // above.
    const user = setup()
    const box = screen.getByLabelText('Add to today')
    await user.type(box, 'gym at 7')
    await user.click(await screen.findByRole('button', { name: 'Make it a note' }))
    expect(fateChip()!.textContent).toMatch(/Note/)

    await user.clear(box)
    await user.type(box, 'gym at 8')
    await waitFor(() => expect(fateChip()?.textContent).toMatch(/Task/))
  })

  it('names the list once — in the picker when there is one', async () => {
    m.lists.mockResolvedValue([list, otherList])
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'gym at 7')
    await screen.findByLabelText('List for the new task')

    // The picker is naming it, so the sentence above does not say it again.
    expect(fateChip()!.textContent).not.toMatch(/on Work/)
    expect(fateChip()!.textContent).toMatch(/other apps/)
  })

  it('forgets the chosen kind once the line is committed', async () => {
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'gym at 7')
    await user.click(await screen.findByRole('button', { name: 'Make it a note' }))
    await user.type(screen.getByLabelText('Add to today'), '{Enter}')
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalled())

    // A fresh dated line reads as a task again: the pin was about that line.
    await user.type(screen.getByLabelText('Add to today'), 'gym at 8')
    await waitFor(() => expect(fateChip()?.textContent).toMatch(/Task/))
  })

  it('puts the task on the list the picker names', async () => {
    m.lists.mockResolvedValue([list, otherList])
    m.createTask.mockResolvedValue(task({ uid: 'new@tasksd', summary: 'gym', list: 'l2' }))
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'gym at 7')

    const picker = await screen.findByLabelText('List for the new task')
    await user.selectOptions(picker, 'l2')
    await user.type(screen.getByLabelText('Add to today'), '{Enter}')

    await waitFor(() => expect(m.createTask).toHaveBeenCalledWith('l2', expect.anything()))
  })

  it('offers no picker when there is only one list to pick', async () => {
    // The box is still ONE input on the fast path. A picker that can only ever
    // answer one way is the friction this surface exists to remove.
    m.createTask.mockResolvedValue(task({ uid: 'new@tasksd', summary: 'gym' }))
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'gym at 7')
    await waitFor(() => expect(fateChip()).not.toBeNull())

    expect(screen.queryByLabelText('List for the new task')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Add to today'), '{Enter}')
    await waitFor(() => expect(m.createTask).toHaveBeenCalledWith('l1', expect.anything()))
  })

  it('never authors a task into a calendar', async () => {
    // `GET /api/lists` answers calendars alongside task lists, and nothing in
    // this app read `is_task_list` outside a test fixture — so the old
    // `lists[0]` was "whatever sits first in the sidebar". On an account whose
    // first collection is a calendar, a dated line authored its VTODO there.
    m.lists.mockResolvedValue([cal, list])
    m.createTask.mockResolvedValue(task({ uid: 'new@tasksd', summary: 'gym' }))
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'gym at 7{Enter}')

    await waitFor(() => expect(m.createTask).toHaveBeenCalled())
    expect(m.createTask).toHaveBeenCalledWith('l1', expect.anything())
    expect(m.createTask).not.toHaveBeenCalledWith('c1', expect.anything())
  })

  it('falls back to a note when the account has no task list at all', async () => {
    // A calendar-only account has nowhere to put a task, so the chip must not
    // promise one — and the swap that would ask for one is offered disabled
    // rather than as a control that silently does nothing.
    m.lists.mockResolvedValue([cal])
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'gym at 7')

    await waitFor(() => expect(fateChip()).not.toBeNull())
    expect(fateChip()!.textContent).toMatch(/Note/)
    expect(screen.getByRole('button', { name: 'Make it a task' })).toBeDisabled()

    await user.type(screen.getByLabelText('Add to today'), '{Enter}')
    // The LITERAL line, "at 7" included — the parser deletes what it reads.
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalledWith(
      today(), expect.objectContaining({ kind: 'note', title: 'gym at 7' })))
    expect(m.createTask).not.toHaveBeenCalled()
  })

  it('promises nothing on a finished day, because it is not there', async () => {
    m.day.mockImplementation(async (d) => plan([entry({ day: d, title: 'Yesterday' })], d))
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Previous day' }))
    await screen.findByText('Yesterday')

    expect(screen.queryByLabelText('Add to today')).not.toBeInTheDocument()
    expect(fateChip()).toBeNull()
    expect(screen.queryByRole('button', { name: /^Make it a/ })).not.toBeInTheDocument()
  })
})

// ── finding habits at all ───────────────────────────────────────────────────

describe('<TodayView> finding habits', () => {
  it('offers them as a word, not only as a glyph', async () => {
    // The control was a bare ↻ whose only human-readable name lived in `title`
    // — a tooltip, which does not exist on a touchscreen. So on a phone the one
    // entry point to the feature was an unexplained symbol.
    setup()
    const btn = await screen.findByRole('button', { name: 'Habits' })
    expect(btn.textContent).toContain('Habits')
    // The glyph is decorative and must stay OUT of the accessible name — this
    // is what keeps the name exactly "Habits" for the four suites that match it
    // exactly, and `getByRole(name:)` above is already asserting it.
    expect(btn.querySelector('[aria-hidden="true"]')?.textContent).toBe('↻')
  })

  it('points at habits from a day with nothing on it', async () => {
    // The account most likely to need the hint is the one where the Habits
    // group is (rightly) absent because there is nothing to put in it.
    const user = setup()
    const link = await screen.findByRole('button', { name: 'set up a habit' })
    await user.click(link)
    expect(await screen.findByRole('dialog', { name: 'Habits' })).toBeInTheDocument()
  })

  it('explains habits on a worked day that has none', async () => {
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    const user = setup()
    await screen.findByText('Water the plants')

    // The empty-day copy is gone — the two traces are mutually exclusive, so
    // the screen never says the same thing twice.
    expect(screen.queryByRole('button', { name: 'set up a habit' })).not.toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Set one up' }))
    expect(await screen.findByRole('dialog', { name: 'Habits' })).toBeInTheDocument()
  })

  it('says nothing about habits on a day that already has some', async () => {
    // The hint is a way IN, not a permanent banner: once the spine is on the
    // screen it is explaining itself.
    m.openDay.mockResolvedValue(plan([
      occurrence({ title: 'Read' }),
      entry({ entry_id: 'e-note', title: 'Water the plants', position: 2 }),
    ]))
    setup()
    await screen.findByText('Water the plants')

    expect(screen.queryByRole('button', { name: 'Set one up' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'set up a habit' })).not.toBeInTheDocument()
  })

  it('offers no way in to habits from a finished day', async () => {
    // The whole sheet is gated on `isToday`, and so are both new traces —
    // nothing done in there could ever show on a day that is a finished record.
    m.day.mockImplementation(async (d) => plan([entry({ day: d, title: 'Yesterday' })], d))
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Previous day' }))
    await screen.findByText('Yesterday')

    expect(screen.queryByRole('button', { name: 'Habits' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Set one up' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'set up a habit' })).not.toBeInTheDocument()
  })
})

// ── telling the three kinds apart ───────────────────────────────────────────

describe('<TodayView> telling the three kinds apart', () => {
  it('gives a note the same left edge as a task and a habit', async () => {
    // THE REGRESSION THIS SUITE EXISTS FOR. A task rendered `.list-dot` and a
    // habit rendered its glyph, both 13px; a note matched neither condition and
    // rendered NOTHING, so its title began 13px left of every neighbour. The
    // assertion is deliberately "every row has exactly one", not "a note has
    // one": one element per row is the property that makes the edge hold, and
    // it is the only spelling a future `kind` cannot quietly fall out of.
    m.tasks.mockResolvedValue([task()])
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'e-task', kind: 'task', list: 'l1', uid: 'u1', title: null, position: 1 }),
      entry({ entry_id: 'e-note', kind: 'note', title: 'Water the plants', position: 2 }),
      occurrence({ entry_id: 'e-hab', title: 'Read', position: 3 }),
    ]))
    setup()
    await screen.findByText('Water the plants')

    const rows = [...document.querySelectorAll('.today-row')]
    expect(rows).toHaveLength(3)
    for (const r of rows) {
      expect(r.querySelectorAll('.today-kind-mark')).toHaveLength(1)
    }
  })

  it('marks a task on a colourless list without leaving it faint', async () => {
    // `.list-dot`'s default background was --fg-faint, so a list nobody had
    // coloured drew a faint dot against a faint rule — and the one distinction
    // that matters here (does this leave the app?) was carried by it. The mark
    // now takes --fg from the stylesheet, so what has to hold is that NO inline
    // background is written when there is no colour to write.
    m.lists.mockResolvedValue([{ ...list, color: null }])
    m.tasks.mockResolvedValue([task()])
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'e-task', kind: 'task', list: 'l1', uid: 'u1', title: null }),
    ]))
    setup()
    await screen.findByText('Ship it')

    const mark = document.querySelector('.today-kind-mark')!
    expect(mark.getAttribute('data-kind')).toBe('task')
    expect((mark.querySelector('.today-kind-box') as HTMLElement).style.background).toBe('')
  })

  it('never wears a bare kind name as a class', () => {
    // A SCAR. The first cut spelled the class list `today-kind-mark ${kind}`,
    // which put a bare `task` class on every task row — and `.task` is the
    // Tasks pane's ROW rule in this same global stylesheet, three hundred lines
    // up. The mark inherited `display: flex` and the row's gutter padding and
    // painted as a 52x19 slab instead of a 7px square. Every test passed: jsdom
    // applies no layout, so nothing in this file could have seen it, and it
    // took running the app to find.
    //
    // Asserted on the SOURCE rather than on a render, because that is where the
    // mistake lives and where it would come back — a template literal dropping
    // an arbitrary string into a global class namespace.
    // Matched on the ATTRIBUTE rather than on the string, so the account of the
    // mistake in TodayRow's own comment — which quotes the bad spelling — does
    // not trip its own test.
    const src = readFileSync(resolve(process.cwd(), 'src/components/TodayView.tsx'), 'utf8')
    expect(src).not.toMatch(/className=\{`today-kind-mark/)
    for (const k of ['task', 'note', 'habit']) {
      expect(src).not.toContain(`className="today-kind-mark ${k}"`)
    }
    // And the attribute that replaced it is actually there.
    expect(src).toContain('data-kind={entry.kind}')
  })

  it('wears the list colour when there is one', async () => {
    m.tasks.mockResolvedValue([task()])
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'e-task', kind: 'task', list: 'l1', uid: 'u1', title: null }),
    ]))
    setup()
    await screen.findByText('Ship it')

    expect((document.querySelector('.today-kind-box') as HTMLElement).style.background)
      .toBeTruthy()
  })

  it('names each kind for assistive tech', async () => {
    // The kind is the one thing a row carries that its title, checkbox and due
    // date do not, and a mixed list is where it matters: a screen reader had no
    // way at all to tell a note from a task.
    m.tasks.mockResolvedValue([task()])
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'e-task', kind: 'task', list: 'l1', uid: 'u1', title: null, position: 1 }),
      entry({ entry_id: 'e-note', kind: 'note', title: 'Water the plants', position: 2 }),
      occurrence({ entry_id: 'e-hab', title: 'Read', position: 3 }),
    ]))
    setup()
    await screen.findByText('Water the plants')

    expect(screen.getByRole('img', { name: 'Task' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Note' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Habit' })).toBeInTheDocument()
  })

  it('names a kind it has never heard of rather than leaving it nameless', async () => {
    // `DayEntryKind` widens silently — api.ts says so, because nothing switches
    // on it exhaustively. A bare lookup would hand assistive tech a nameless
    // role="img" on every row of the new kind, and the old two-conditional
    // markup would have given it no mark and no left edge either.
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'e-x', kind: 'ritual' as never, title: 'Something new' }),
    ]))
    setup()
    await screen.findByText('Something new')

    expect(screen.getByRole('img', { name: 'Entry' })).toBeInTheDocument()
    expect(document.querySelectorAll('.today-row .today-kind-mark')).toHaveLength(1)
  })

  it('runs the same column down the suggestions', async () => {
    // One left edge for the whole screen: a suggestion is a task, and a group
    // whose rows start somewhere else stops reading as part of the same list.
    m.tasks.mockResolvedValue([task({ due: today(), due_is_date: true })])
    setup()
    await screen.findByRole('button', { name: /Add Ship it to today/ })

    const sug = document.querySelector('.today-sug')!
    expect(sug.querySelectorAll('.today-kind-mark[data-kind="task"]')).toHaveLength(1)
  })
})

// ── habits on the day ───────────────────────────────────────────────────────

describe('<TodayView> habits', () => {
  it('paints them in their own group above the rest of the day', async () => {
    // The habit carries the LATER position deliberately: reading order alone
    // would put the note first, so a test built on a habit that already sorts
    // to the top would pass whether or not the partition exists.
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'n1', title: 'Water the plants', position: 1 }),
      occurrence({ entry_id: 'h1', title: 'Read', position: 2 }),
    ]))
    setup()
    await screen.findByText('Read')

    expect(habitTitles()).toEqual(['Read'])
    expect(rowTitles()).toEqual(['Water the plants'])
    const group = screen.getByRole('list', { name: 'Habits' })
    const note = screen.getByText('Water the plants')
    expect(group.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING,
      'the habits group did not come first').toBeTruthy()
  })

  it('names the day’s own rows, so the group above is not the only boundary',
    async () => {
      // The habits group has carried a heading since it arrived and the rows
      // below it never did, so the whole statement that the spine is not part
      // of the day was ONE heavier hairline under the last habit. Every other
      // thing about the two lists is identical by design — same row, same
      // checkbox, same left edge, same type — so four habits followed by four
      // tasks read as eight rows with a slightly darker line in the middle.
      m.openDay.mockResolvedValue(plan([
        entry({ entry_id: 'n1', title: 'Water the plants', position: 1 }),
        occurrence({ entry_id: 'h1', title: 'Read', position: 2 }),
      ]))
      setup()
      await screen.findByText('Read')

      // The first two headings on the tab, in order. Sliced rather than
      // compared whole because the suggestion groups and "On the calendar"
      // paint below and are not what this is about.
      const headings = [...document.querySelectorAll('.section-label')]
        .map((n) => n.textContent)
      expect(headings.slice(0, 2)).toEqual(['Habits', 'The day'])

      // And the heading is attached to the list for anyone who cannot see that
      // it sits above it — the same job `aria-label` does for the habits group,
      // and the reason a visible heading alone was not enough there either.
      const day = screen.getByRole('list', { name: 'The day' })
      expect([...day.querySelectorAll('.today-title')].map((n) => n.textContent))
        .toEqual(['Water the plants'])
    })

  it('keeps that heading on a day with no habits at all', async () => {
    // Unconditional, deliberately. Gated on the habits group being present, the
    // tab would grow a heading on Tuesday and lose it on Wednesday — its shape
    // would depend on whether a habit happened to be due, which is exactly the
    // kind of moving furniture the surface someone opens every morning should
    // not have. It is NOT the "no heading over nothing" rule the habits group
    // and the hint below it follow: that guards an EMPTY group, and this is
    // gated on the rows it names.
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'n1', title: 'Water the plants' }),
    ]))
    setup()
    await screen.findByText('Water the plants')

    expect([...document.querySelectorAll('.section-label')].map((n) => n.textContent))
      .toContain('The day')
    // …and there is still nothing advertising an empty habits group over it.
    expect(screen.queryByRole('list', { name: 'Habits' })).not.toBeInTheDocument()
  })

  it('still counts them in the day totals', async () => {
    m.openDay.mockResolvedValue(plan([
      occurrence({ entry_id: 'h1' }),
      entry({ entry_id: 'n1', title: 'Water the plants' }),
    ]))
    m.patchDayEntry.mockResolvedValue(
      occurrence({ entry_id: 'h1', done_at: '2026-08-21T10:00:00.000Z' }))
    const user = setup()

    // The figure and the ROWS UNDER IT, together: "2 on the day" over a screen
    // showing one row is the one number here nobody could reconcile, and the
    // figure on its own is computed from the fetched entries — it would read
    // the same with the habits group deleted, which is the state this is here
    // to rule out.
    expect(await screen.findByText(/2 open · 2 on the day/)).toBeInTheDocument()
    expect([...habitTitles(), ...rowTitles()]).toEqual(['Read', 'Water the plants'])

    // And the open half moves with the habit, down the same `!done_at` arm a
    // note takes — ticked from the row on screen, which is the only place the
    // occurrence can be ticked from.
    await user.click(screen.getByRole('button', { name: 'Check Read' }))
    expect(await screen.findByText(/1 open · 2 on the day/)).toBeInTheDocument()
  })

  it('ticks on the entry itself, never through the task API', async () => {
    m.openDay.mockResolvedValue(plan([occurrence({ entry_id: 'h1' })]))
    m.patchDayEntry.mockResolvedValue(
      occurrence({ entry_id: 'h1', done_at: '2026-08-21T10:00:00.000Z' }))
    const user = setup()
    await screen.findByText('Read')

    await user.click(screen.getByRole('button', { name: 'Check Read' }))

    // A habit occurrence exists nowhere but in the day, exactly like a note, so
    // the day is the only place its doneness can live. There is no VTODO behind
    // it to complete — a habit never reaches Radicale at all.
    await waitFor(() =>
      expect(m.patchDayEntry).toHaveBeenCalledWith(today(), 'h1', { done: true }))
    expect(m.complete).not.toHaveBeenCalled()
    await waitFor(() =>
      expect(document.querySelector('.today-habit')?.className).toContain('done'))
  })

  it('never offers one as a suggestion', async () => {
    m.tasks.mockResolvedValue([task({ uid: 'a', summary: 'Stretch', due: today() })])
    m.openDay.mockResolvedValue(plan([occurrence({ title: 'Read' })]))
    setup()

    // The control: the suggestion lists are working on this render.
    expect(await screen.findByRole('button', { name: 'Add Stretch to today' }))
      .toBeInTheDocument()
    // "Read" is on this screen EXACTLY ONCE, and the one is the habit row.
    // Counted rather than merely looked for: "no Add Read button" and "the
    // suggestions read Stretch" are both true of a screen with no habit on it
    // at all, so on their own they would hold with the habits group deleted and
    // pin nothing. A habit that leaked into the lists below would be a second
    // one, and a habit that stopped rendering would be none.
    const reads = [...document.querySelectorAll('.today-title')]
      .filter((t) => t.textContent === 'Read')
    expect(reads).toHaveLength(1)
    expect(reads[0].closest('.today-row')?.className).toContain('today-habit')
    // A habit is scheduled, not suggested. Offering to add something that is
    // already coming back tomorrow offers a decision already made.
    expect(screen.queryByRole('button', { name: 'Add Read to today' }))
      .not.toBeInTheDocument()
    expect([...document.querySelectorAll('.today-sug .today-title')]
      .map((t) => t.textContent)).toEqual(['Stretch'])
  })
})

// ── the weekly count ────────────────────────────────────────────────────────

describe('<TodayView> the weekly count', () => {
  // Friday, so the week has four days behind it. Pinned rather than derived
  // from the real clock because a suite that happened to run on a Monday would
  // have no prior days to count and every assertion here would pass vacuously.
  // The zone is America/New_York, from vite.config.ts.
  const FRIDAY = new Date(2026, 7, 21, 9, 0)
  const MON = '2026-08-17'
  const TUE = '2026-08-18'
  const WED = '2026-08-19'

  /** One day of the week as the range read returns it: a plan holding a single
   *  occurrence of the habit under test. */
  const on = (day: string, o: Partial<DayEntry> = {}) =>
    plan([occurrence({ entry_id: `h-${day}`, day, ...o })], day)

  const DONE = '2026-08-17T09:00:00.000Z'

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(FRIDAY)
  })
  afterEach(() => { vi.useRealTimers() })

  it('counts the occurrences that exist, not the weekdays in the week', async () => {
    m.days.mockResolvedValue([on(MON, { done_at: DONE }), on(WED)])
    m.openDay.mockResolvedValue(plan([occurrence()]))
    setup()

    // Monday done, Wednesday not, today not: three occurrences, one ticked.
    // Tuesday and Thursday have no plan at all, which is the whole argument for
    // this denominator — an absent row could mean the habit was not scheduled,
    // or was missed, or that THE APP WAS NEVER OPENED THAT DAY, and nothing on
    // the wire can tell those apart afterwards.
    expect(await screen.findByText('1 of 3 this week')).toBeInTheDocument()
    // "1 of 5" is what counting scheduled weekdays would have said, and it
    // would be charging the owner for two days they were never asked about.
    expect(screen.queryByText(/of 5 this week/)).not.toBeInTheDocument()

    // ONE read for every habit on the screen AND for the "still open from a
    // recent plan" group below it, and `days` rather than `openDay`: the window
    // asserted below is `[day - 14, day + 1)`, fifteen days, and reading it must
    // not OPEN the fourteen of them the owner is not looking at.
    //
    // The window is deliberately WIDER than the week this count spans — it is
    // the look-back's fortnight, LOOKBACK_DAYS back from the day on screen —
    // and `habitWeek` filters it down to the week itself. The "1 of 3" above is
    // what pins that filter: without it Monday the 10th's occurrence would be
    // in the range read and in the count.
    expect(m.days).toHaveBeenCalledTimes(1)
    expect(m.days).toHaveBeenCalledWith('2026-08-07', '2026-08-22')
  })

  it('leaves a day before this Monday out of the count, though it is in the read',
    async () => {
      // The fortnight the one range read spans reaches back past this week, so
      // the count has to cut it at Monday. Without that cut this reads "2 of 4"
      // — a habit's weekly figure quietly counting a fortnight, and jumping
      // every Monday for no reason the owner could see.
      m.days.mockResolvedValue([on('2026-08-13'), on(MON, { done_at: DONE }), on(WED)])
      m.openDay.mockResolvedValue(plan([occurrence()]))
      setup()

      expect(await screen.findByText('1 of 3 this week')).toBeInTheDocument()
      expect(screen.queryByText(/of 4 this week/)).not.toBeInTheDocument()
      // …and it really was in the window that was fetched.
      expect(m.days).toHaveBeenCalledWith('2026-08-07', '2026-08-22')
    })

  it('says nothing at all when only one occurrence exists', async () => {
    m.days.mockResolvedValue([])
    m.openDay.mockResolvedValue(plan([occurrence()]))
    setup()
    await screen.findByText('Read')
    // A Monday morning has nothing to report. "0 of 1 this week" is a
    // scoreboard opened on the first play.
    expect(screen.queryByText(/this week/)).not.toBeInTheDocument()
  })

  it('starts reporting at the second occurrence', async () => {
    m.days.mockResolvedValue([on(MON, { done_at: DONE })])
    m.openDay.mockResolvedValue(plan([occurrence()]))
    setup()
    expect(await screen.findByText('1 of 2 this week')).toBeInTheDocument()
  })

  it('leaves a dropped occurrence out of BOTH halves', async () => {
    m.days.mockResolvedValue([
      on(MON, { done_at: DONE }),
      // Ticked and THEN dropped, which is what makes this the interesting case:
      // an implementation that only removed it from the denominator would still
      // count it in the numerator and report 2 of 3 for the wrong reason.
      on(TUE, { done_at: DONE, dropped_at: '2026-08-18T20:00:00.000Z' }),
      on(WED, { done_at: DONE }),
    ])
    m.openDay.mockResolvedValue(plan([occurrence()]))
    setup()

    // "I decided not to do this" is a decision the day recorded, not a failure
    // to act on one. Counting it whole says 3 of 4; counting only its
    // denominator says 2 of 4. The record says 2 of 3.
    expect(await screen.findByText('2 of 3 this week')).toBeInTheDocument()
  })

  it('moves on the click, from the day already in hand', async () => {
    m.days.mockResolvedValue([on(MON, { done_at: DONE }), on(WED)])
    m.openDay.mockResolvedValue(plan([occurrence({ entry_id: 'h1' })]))
    m.patchDayEntry.mockResolvedValue(
      occurrence({ entry_id: 'h1', done_at: '2026-08-21T10:00:00.000Z' }))
    const user = setup({ advanceTimers: vi.advanceTimersByTime })
    expect(await screen.findByText('1 of 3 this week')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Check Read' }))

    // Today's rows come from the plan this view is holding, which has already
    // absorbed the optimistic tick — so the count moves now rather than after a
    // round trip. It also proves the range read's copy of today is REPLACED and
    // not added to: counting both would have said 2 of 4.
    expect(await screen.findByText('2 of 3 this week')).toBeInTheDocument()
    expect(m.days).toHaveBeenCalledTimes(1)
  })
})

// ── the habits sheet ────────────────────────────────────────────────────────

describe('<TodayView> the habits sheet', () => {
  const openSheet = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(await screen.findByRole('button', { name: 'Habits' }))
    return screen.findByRole('dialog', { name: 'Habits' })
  }

  it('lists the rules, paused ones included, with the days they come up on',
    async () => {
      m.habits.mockResolvedValue([
        habit(),
        habit({ id: 'hb2', title: 'Stretch', days: 'mon,wed', paused_at: '2026-08-20T08:00:00.000Z' }),
      ])
      const user = setup()
      await openSheet(user)

      expect(await screen.findByLabelText('Rename Read')).toHaveValue('Read')
      // A paused habit is on this list precisely because this is the screen
      // that un-pauses it.
      expect(screen.getByRole('button', { name: 'Resume Stretch' })).toBeInTheDocument()
      // '' is every day, and the chips say so rather than sitting dark — a row
      // of unlit chips beside the words "every day" reads as the opposite of
      // what it means.
      expect(screen.getByRole('button', { name: 'Mon for Read' }))
        .toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByRole('button', { name: 'Sun for Read' }))
        .toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByRole('button', { name: 'Wed for Stretch' }))
        .toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByRole('button', { name: 'Tue for Stretch' }))
        .toHaveAttribute('aria-pressed', 'false')
    })

  it('adds one', async () => {
    const user = setup()
    const sheet = await openSheet(user)
    await user.type(screen.getByLabelText('New habit'), 'Stretch')
    // Scoped to the sheet: the quick-add form behind it has an "Add" too.
    await user.click(within(sheet).getByRole('button', { name: 'Add' }))

    await waitFor(() => expect(m.createHabit).toHaveBeenCalledWith({ title: 'Stretch' }))
    expect(await screen.findByLabelText('Rename Stretch')).toBeInTheDocument()
    expect(screen.getByLabelText('New habit')).toHaveValue('')
  })

  it('renames one', async () => {
    m.habits.mockResolvedValue([habit()])
    const user = setup()
    await openSheet(user)
    const name = await screen.findByLabelText('Rename Read')

    await user.clear(name)
    await user.type(name, 'Read a chapter')
    await user.tab()                       // committing on blur, as Sidebar does

    await waitFor(() =>
      expect(m.patchHabit).toHaveBeenCalledWith('hb1', { title: 'Read a chapter' }))
  })

  it('pauses and resumes one', async () => {
    m.habits.mockResolvedValue([habit()])
    const user = setup()
    await openSheet(user)

    await user.click(await screen.findByRole('button', { name: 'Pause Read' }))
    await waitFor(() => expect(m.patchHabit).toHaveBeenCalledWith('hb1', { paused: true }))
    // `paused` is a real boolean on the wire, not an omission: resuming has to
    // be spellable, which is why it is tri-state server-side.
    await user.click(await screen.findByRole('button', { name: 'Resume Read' }))
    await waitFor(() => expect(m.patchHabit).toHaveBeenCalledWith('hb1', { paused: false }))
  })

  it('reschedules one, in the order the server canonicalises to', async () => {
    m.habits.mockResolvedValue([habit({ days: '' })])
    const user = setup()
    await openSheet(user)

    await user.click(await screen.findByRole('button', { name: 'Wed for Read' }))

    // '' is all seven, so turning one off leaves the other six — written
    // mon..sun, which is what the server re-orders to, so what we send is what
    // comes back and the row does not appear to change under the owner.
    await waitFor(() => expect(m.patchHabit)
      .toHaveBeenCalledWith('hb1', { days: 'mon,tue,thu,fri,sat,sun' }))
  })

  it('reads a second quick chip click against the first one, not against the wire',
    async () => {
      m.habits.mockResolvedValue([habit({ days: '' })])
      // Held open, so the second click happens with the first PATCH still in
      // flight — which is the whole of the bug. A `days` derived from the row
      // as the server last sent it is derived from the PRE-patch schedule for
      // as long as the reply takes.
      let settle: (h: Habit) => void = () => {}
      m.patchHabit.mockReturnValueOnce(new Promise((r) => { settle = r }) as never)
      const user = setup()
      await openSheet(user)

      await user.click(await screen.findByRole('button', { name: 'Mon for Read' }))
      await waitFor(() => expect(m.patchHabit)
        .toHaveBeenCalledWith('hb1', { days: 'tue,wed,thu,fri,sat,sun' }))
      // Unlit before any reply: that optimistic row is what the next click has
      // to read, and it is also what the owner is looking at when they make it.
      expect(screen.getByRole('button', { name: 'Mon for Read' }))
        .toHaveAttribute('aria-pressed', 'false')

      await user.click(screen.getByRole('button', { name: 'Wed for Read' }))

      // Monday is NOT in it. Derived from the wire's row, both clicks would
      // have started from all seven and this one would have sent Monday back
      // on — a change the owner made, undone by last-write-wins.
      await waitFor(() => expect(m.patchHabit)
        .toHaveBeenLastCalledWith('hb1', { days: 'tue,thu,fri,sat,sun' }))
      expect(screen.getByRole('button', { name: 'Wed for Read' }))
        .toHaveAttribute('aria-pressed', 'false')

      // And the first click's reply, arriving last, knows nothing of the second
      // — settling the row on it would put Wednesday back for as long as the
      // second reply took.
      await act(async () => { settle(habit({ days: 'tue,wed,thu,fri,sat,sun' })) })
      expect(screen.getByRole('button', { name: 'Wed for Read' }))
        .toHaveAttribute('aria-pressed', 'false')
      expect(screen.getByRole('button', { name: 'Mon for Read' }))
        .toHaveAttribute('aria-pressed', 'false')
    })

  it('reads clearing the last day as clearing the restriction', async () => {
    m.habits.mockResolvedValue([habit({ days: 'mon' })])
    const user = setup()
    await openSheet(user)

    await user.click(await screen.findByRole('button', { name: 'Mon for Read' }))

    // The vocabulary has no way to say "no days" and needs none: the chips are
    // a restriction, so clearing the last of them clears the restriction rather
    // than asking for a habit that never comes up.
    await waitFor(() => expect(m.patchHabit).toHaveBeenCalledWith('hb1', { days: '' }))
  })

  it('warns that past days keep their occurrences, then deletes', async () => {
    m.habits.mockResolvedValue([habit()])
    const user = setup()
    await openSheet(user)

    await user.click(await screen.findByRole('button', { name: 'Delete Read' }))
    // Two presses, and the second is offered beside the warning rather than
    // instead of it: deleting a habit removes the RULE, and every day it has
    // already run on keeps the line it put there.
    expect(screen.getByText(/keeps the line it put there/i)).toBeInTheDocument()
    expect(m.deleteHabit).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Confirm delete Read' }))
    await waitFor(() => expect(m.deleteHabit).toHaveBeenCalledWith('hb1'))
    await waitFor(() =>
      expect(screen.queryByLabelText('Rename Read')).not.toBeInTheDocument())
  })

  it('closes on an Escape dispatched at the window', async () => {
    // At the WINDOW, not at the focused element: a listener bound to the dialog
    // only fires while focus is inside it, and with no focus trap that is
    // exactly the state a keyboard user needs the escape hatch from. See
    // `useEscape` in hooks.ts, which is the binding every other overlay here
    // uses and the one this sheet reuses rather than re-inventing.
    const user = setup()
    await openSheet(user)
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Habits' })).not.toBeInTheDocument())
  })

  it('takes its Escape listener with it when it closes', async () => {
    const add = vi.spyOn(window, 'addEventListener')
    const remove = vi.spyOn(window, 'removeEventListener')
    try {
      const user = setup()
      await openSheet(user)
      // Indexed rather than `.at(-1)`: this project targets ES2020, where
      // `Array.prototype.at` does not exist.
      const keydowns = add.mock.calls.filter(([t]) => t === 'keydown')
      expect(keydowns.length, 'the sheet registered no keydown listener at the window')
        .toBeGreaterThan(0)
      const handler = keydowns[keydowns.length - 1][1]

      await user.click(screen.getByRole('button', { name: 'Close' }))
      await waitFor(() =>
        expect(screen.queryByRole('dialog', { name: 'Habits' })).not.toBeInTheDocument())

      // The EXACT handler that was registered, not merely "a keydown listener
      // was removed". One that outlives the sheet closes the next dialog to
      // open, or sets state on a tree that is gone.
      expect(remove.mock.calls.some(([t, fn]) => t === 'keydown' && fn === handler))
        .toBe(true)
    } finally {
      add.mockRestore()
      remove.mockRestore()
    }
  })
})

// ── pure helpers ────────────────────────────────────────────────────────────

// ── painting before the server answers ──────────────────────────────────────
//
// The two halves of one property, and the two the Today tab was missing while
// every other data surface in the app had both: what is on screen in the gap
// between a MOUNT and the read that fills it, and in the gap between a GESTURE
// and the write that settles it.
//
// The first gap is the one only this tab has. Every other task surface renders
// a query over `tasks`, which `cache.ts` has mirrored to disk all along, so it
// paints from the mirror on the first frame. A day plan exists nowhere but in
// `day_plan` — that is the whole point of the tab (see TodayView.tsx's header)
// — so with nothing cached there was nothing to paint until
// `POST /api/day/{today}/open` answered, and that call derives its snapshot
// from CalDAV. Switching tabs unmounts the view, so every return replayed it.

describe('<TodayView> the disk mirror', () => {
  it('paints the cached day on the first frame, then the server’s', async () => {
    setCacheUser('nick')
    cacheDayPlan(plan([entry({ entry_id: 'cached', title: 'From the mirror' })]))
    const open = held<DayPlan>()
    m.openDay.mockReturnValue(open.promise)

    setup()
    // Before anything has answered at all. This is the frame that used to be
    // empty, on a cold load and on every switch back to the tab.
    expect(rowTitles()).toEqual(['From the mirror'])

    await act(async () => {
      open.land(plan([entry({ entry_id: 'live', title: 'From the server' })]))
    })
    // Replaced, not merged: the server is the source of truth and the mirror is
    // only what to show until it answers.
    await waitFor(() => expect(rowTitles()).toEqual(['From the server']))
  })

  it('is keyed to the day, so yesterday’s rows never paint under today', async () => {
    setCacheUser('nick')
    cacheDayPlan(plan([entry({ title: 'Yesterday' })], inDays(-1)))
    m.openDay.mockReturnValue(held<DayPlan>().promise)

    setup()
    // The rows on screen and the day every write carries have to be the same
    // day or the surface lies — so a blob written for another day is a miss,
    // not a head start.
    await waitFor(() => expect(m.openDay).toHaveBeenCalled())
    expect(rowTitles()).toEqual([])
  })

  it('mirrors the day it read, so the next mount has it', async () => {
    setCacheUser('nick')
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    setup()
    await screen.findByText('Water the plants')

    // On the trailing edge, so a burst of optimistic paints — ticking four
    // rows, dragging one — costs one write rather than one per click.
    await waitFor(
      () => expect(readCachedDayPlan(today())?.entries ?? []).toHaveLength(1),
      { timeout: 3000 })
  })

  it('mirrors an optimistic add too, before the server has confirmed it', async () => {
    setCacheUser('nick')
    m.addDayEntry.mockReturnValue(held<DayEntry>().promise)
    const user = setup()
    await user.type(await screen.findByLabelText('Add to today'), 'call mum{Enter}')
    await waitFor(() => expect(rowTitles()).toEqual(['call mum']))

    // Deliberate, and the same call `data.tsx` makes for tasks: coming back to
    // the tab straight after adding a line should show the line.
    await waitFor(
      () => expect(readCachedDayPlan(today())?.entries.map((e) => e.title))
        .toEqual(['call mum']),
      { timeout: 3000 })
  })

  it('writes only today, so a look-back cannot evict what a mount reads', async () => {
    setCacheUser('nick')
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    m.day.mockImplementation(async (d) => plan([entry({ entry_id: 'y', title: 'Back then' })], d))
    const user = setup()
    await screen.findByText('Water the plants')
    await waitFor(
      () => expect(readCachedDayPlan(today())?.entries ?? []).toHaveLength(1),
      { timeout: 3000 })

    await user.click(screen.getByRole('button', { name: 'Previous day' }))
    await screen.findByText('Back then')

    // The mirror holds ONE day and the tab always mounts on today (`day` is
    // seeded from the wall clock, so a look-back never survives a tab switch).
    // A past day written here would only evict the entry that gets read.
    await new Promise((r) => setTimeout(r, 600))
    expect(readCachedDayPlan(inDays(-1))).toBeNull()
    expect(readCachedDayPlan(today())?.entries ?? []).toHaveLength(1)
  })

  it('paints the cached habit rules the moment the sheet opens', async () => {
    setCacheUser('nick')
    cacheHabits([habit({ id: 'hb1', title: 'Read' })])
    m.habits.mockReturnValue(held<Habit[]>().promise)
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Habits' }))
    await screen.findByRole('dialog', { name: 'Habits' })

    // The sheet is opened on demand rather than mounted with the tab, so its
    // fetch starts on the click: without a mirror the dialog was empty for a
    // round trip every single time it was opened.
    expect(screen.getByLabelText('Rename Read')).toBeInTheDocument()
  })

  it('still refuses the add box when the read failed and there is nothing cached',
    async () => {
      // The gate moved from `dayError` to "the read failed AND there is nothing
      // to paint", because the mirror pulled those two apart. This is the half
      // that must not have moved: with no plan for this day every optimistic
      // writer is a no-op, so an add would reach the server, succeed, and paint
      // nothing.
      m.openDay.mockRejectedValue(new Error('boom'))
      setup()
      await waitFor(() => expect(screen.getByLabelText('Add to today')).toBeDisabled())
    })

  it('accepts the add box when the read failed but the mirror has the day', async () => {
    setCacheUser('nick')
    cacheDayPlan(plan([entry({ entry_id: 'cached', title: 'From the mirror' })]))
    m.openDay.mockRejectedValue(new Error('boom'))
    const user = setup()

    // Refusing to write to a day that is visibly on the screen would be
    // refusing for a reason the screen contradicts — and the add is safe
    // against a stale snapshot besides (`add_day_entry` is idempotent on
    // (day, task) and on (day, note text)).
    const box = await screen.findByLabelText('Add to today')
    await waitFor(() => expect(box).toBeEnabled())
    await user.type(box, 'call mum{Enter}')
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalledWith(
      today(), expect.objectContaining({ kind: 'note', title: 'call mum' })))
    expect(rowTitles()).toEqual(['From the mirror', 'call mum'])
  })
})

// ── the writes, and the frame after the gesture ────────────────────────────

describe('<TodayView> painting a write before it lands', () => {

  it('puts a typed task on the day before the VTODO has been written', async () => {
    // The commonest gesture on the tab, and the one write that was not
    // optimistic: a line with a date in it AUTHORS a task and then points the
    // day at it, and the day row used to wait for BOTH round trips. The box
    // cleared and the screen showed nothing for the length of a CalDAV write.
    const create = held<Task>()
    m.createTask.mockReturnValue(create.promise)
    const user = setup()
    await user.type(await screen.findByLabelText('Add to today'), 'gym at 7{Enter}')

    await waitFor(() => expect(m.createTask).toHaveBeenCalled())
    const cid = (m.createTask.mock.calls[0][1] as { client_id: string }).client_id
    // On the day while the task is still being written, reading its title off
    // the stand-in `data.tsx::create` painted into `tasks` — the two agree
    // because both are keyed on the uid the client_id derives (`uidFor`).
    await waitFor(() => expect(rowTitles()).toEqual(['gym']))
    expect(m.addDayEntry).not.toHaveBeenCalled()

    await act(async () => { create.land(task({ uid: uidFor(cid), summary: 'gym' })) })
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalledWith(
      today(), expect.objectContaining({ kind: 'task', list: 'l1', uid: uidFor(cid) })))
    // …and it did not flicker on the way through: the row the create settles
    // into is the row that was already there.
    expect(rowTitles()).toEqual(['gym'])
  })

  it('takes the painted row back off when the task create fails', async () => {
    const create = held<Task>()
    m.createTask.mockReturnValue(create.promise)
    const user = setup()
    await user.type(await screen.findByLabelText('Add to today'), 'gym at 7{Enter}')

    // Painted first — that is the point of the change, and it is what makes
    // the removal below a rollback rather than a no-op.
    await waitFor(() => expect(rowTitles()).toEqual(['gym']))

    await act(async () => { create.fail(new Error('boom')) })

    // No task, so nothing for the row to point at. The line goes back in the
    // box, which is what makes the retry a keystroke away.
    await waitFor(() => expect(rowTitles()).toEqual([]))
    expect(m.addDayEntry).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Add to today')).toHaveValue('gym at 7')
  })

  it('closes the planning ritual on the press, not a round trip later', async () => {
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    const patch = held<DayPlan>()
    m.patchDay.mockReturnValue(patch.promise)
    const user = setup()
    await screen.findByText('Water the plants')

    await user.click(screen.getByRole('button', { name: 'Plan my day' }))
    const dialog = await screen.findByRole('dialog', { name: 'Plan your day' })
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(within(dialog).getByRole('button', { name: 'Start the day' }))

    // The last press of a three-step flow. A round trip spent with the overlay
    // still standing over the day reads as a flow that has hung.
    await waitFor(() => expect(
      screen.queryByRole('dialog', { name: 'Plan your day' })).not.toBeInTheDocument())
    expect(m.patchDay).toHaveBeenCalledWith(today(), { committed: true })
    // The band is gated on the day not having been begun, and the day knows it
    // has been — though nothing has answered yet.
    expect(screen.queryByRole('button', { name: 'Plan my day' })).not.toBeInTheDocument()

    await act(async () => {
      patch.land(plan([], today(), { committed_at: `${today()}T08:00:00.000Z` }))
    })
  })

  it('puts the day back to un-begun when the commit is refused', async () => {
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    const patch = held<DayPlan>()
    m.patchDay.mockReturnValue(patch.promise)
    const user = setup()
    await screen.findByText('Water the plants')

    await user.click(screen.getByRole('button', { name: 'Plan my day' }))
    const dialog = await screen.findByRole('dialog', { name: 'Plan your day' })
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(within(dialog).getByRole('button', { name: 'Start the day' }))

    // Begun on the press, so the nudge is gone…
    await waitFor(() => expect(
      screen.queryByRole('button', { name: 'Plan my day' })).not.toBeInTheDocument())

    await act(async () => { patch.fail(new Error('boom')) })

    // …and back when the write is refused. `guard` has raised the toast; the
    // screen must not go on claiming a day that was never begun.
    expect(await screen.findByRole('button', { name: 'Plan my day' })).toBeInTheDocument()
  })

  it('settles only the field it wrote, so one reply cannot undo another', async () => {
    // `patchDayEntry` answers with the WHOLE row, and settling all of it meant
    // each reply carried an opinion about every other field. A tick and an
    // estimate typed a moment apart on one row therefore raced, and whichever
    // replied last wrote its own idea of the other's field back.
    m.openDay.mockResolvedValue(plan([entry({ entry_id: 'e1', title: 'Water the plants' })]))
    const tick = held<DayEntry>()
    m.patchDayEntry.mockImplementation((_d, id, body) => (
      'done' in body
        ? tick.promise
        : Promise.resolve(entry({
          entry_id: id,
          estimate_minutes: body.estimate_minutes === -1
            ? null : body.estimate_minutes ?? null,
        }))))
    const user = setup()
    await screen.findByText('Water the plants')

    await user.click(screen.getByRole('button', { name: 'Check Water the plants' }))
    await user.click(screen.getByRole('button', { name: 'Estimate Water the plants' }))
    await user.type(screen.getByLabelText('Minutes for Water the plants'), '30{Enter}')
    await waitFor(() => expect(
      screen.getByRole('button', { name: /estimated at/ })).toBeInTheDocument())

    // The tick's reply lands LAST, carrying the row as it stood before the
    // estimate was typed.
    await act(async () => {
      tick.land(entry({
        entry_id: 'e1', title: 'Water the plants',
        done_at: `${today()}T10:00:00.000Z`, estimate_minutes: null,
      }))
    })

    // Both survive: the tick settled its stamp and nothing else.
    expect(screen.getByRole('button', { name: /estimated at/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Uncheck Water the plants' }))
      .toHaveAttribute('aria-pressed', 'true')
  })
})

describe('<TodayView> the habits sheet, before the server answers', () => {
  const openSheet = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(await screen.findByRole('button', { name: 'Habits' }))
    return screen.findByRole('dialog', { name: 'Habits' })
  }

  it('paints a new rule on the press, with its controls disabled until it lands',
    async () => {
      const create = held<Habit>()
      m.createHabit.mockReturnValue(create.promise)
      const user = setup()
      const sheet = await openSheet(user)
      await user.type(screen.getByLabelText('New habit'), 'Stretch')
      await user.click(within(sheet).getByRole('button', { name: 'Add' }))

      // On screen before the rule exists, with the box already empty for the
      // next one — and with every control off, because each of them names an id
      // only this browser knows.
      const name = await screen.findByLabelText('Rename Stretch')
      expect(name).toBeDisabled()
      expect(screen.getByRole('button', { name: 'Delete Stretch' })).toBeDisabled()
      expect(screen.getByRole('button', { name: 'Mon for Stretch' })).toBeDisabled()
      expect(screen.getByLabelText('New habit')).toHaveValue('')

      await act(async () => { create.land(habit({ id: 'hb-new', title: 'Stretch' })) })
      expect(screen.getByLabelText('Rename Stretch')).toBeEnabled()
    })

  it('takes a refused rule back off and puts the line back', async () => {
    const create = held<Habit>()
    m.createHabit.mockReturnValue(create.promise)
    const user = setup()
    const sheet = await openSheet(user)
    await user.type(screen.getByLabelText('New habit'), 'Stretch')
    await user.click(within(sheet).getByRole('button', { name: 'Add' }))

    // Painted, and the box cleared behind it, before any of this.
    await screen.findByLabelText('Rename Stretch')
    expect(screen.getByLabelText('New habit')).toHaveValue('')

    await act(async () => { create.fail(new Error('boom')) })

    await waitFor(() =>
      expect(screen.queryByLabelText('Rename Stretch')).not.toBeInTheDocument())
    expect(screen.getByLabelText('New habit')).toHaveValue('Stretch')
  })

  it('does not overwrite the next line with a refused one', async () => {
    // The line goes back only if the field is still EMPTY. Restoring it over
    // something already being typed would be the rollback doing more damage
    // than the failure it is undoing.
    const create = held<Habit>()
    m.createHabit.mockReturnValue(create.promise)
    const user = setup()
    const sheet = await openSheet(user)
    await user.type(screen.getByLabelText('New habit'), 'Stretch')
    await user.click(within(sheet).getByRole('button', { name: 'Add' }))
    await screen.findByLabelText('Rename Stretch')
    await user.type(screen.getByLabelText('New habit'), 'Walk')

    await act(async () => { create.fail(new Error('boom')) })

    await waitFor(() =>
      expect(screen.queryByLabelText('Rename Stretch')).not.toBeInTheDocument())
    expect(screen.getByLabelText('New habit')).toHaveValue('Walk')
  })

  it('does not mirror a rule the server has not minted an id for yet', async () => {
    // A pending row wears an id only this browser has heard of, and `pending`
    // is session state — so a mirror written mid-flight would paint that row
    // back on the next open with its controls enabled, every one of them
    // naming an id the server can only 404.
    setCacheUser('nick')
    const create = held<Habit>()
    m.createHabit.mockReturnValue(create.promise)
    const user = setup()
    const sheet = await openSheet(user)
    await user.type(screen.getByLabelText('New habit'), 'Stretch')
    await user.click(within(sheet).getByRole('button', { name: 'Add' }))
    await screen.findByLabelText('Rename Stretch')

    // Well past the debounce, and still nothing.
    await new Promise((r) => setTimeout(r, 600))
    expect(readCachedHabits()).toBeNull()

    await act(async () => { create.land(habit({ id: 'hb-new', title: 'Stretch' })) })

    // …and the settle a beat later re-runs the write with the real row.
    await waitFor(() => expect(readCachedHabits()?.map((h) => h.id)).toEqual(['hb-new']),
      { timeout: 3000 })
  })

  it('takes a deleted rule off on the press', async () => {
    m.habits.mockResolvedValue([habit(), habit({ id: 'hb2', title: 'Stretch' })])
    m.deleteHabit.mockReturnValue(held<null>().promise)
    const user = setup()
    await openSheet(user)

    await user.click(await screen.findByRole('button', { name: 'Delete Read' }))
    await user.click(screen.getByRole('button', { name: 'Confirm delete Read' }))

    await waitFor(() =>
      expect(screen.queryByLabelText('Rename Read')).not.toBeInTheDocument())
    expect(screen.getByLabelText('Rename Stretch')).toBeInTheDocument()
  })

  it('puts a refused delete back in its own place', async () => {
    m.habits.mockResolvedValue([habit(), habit({ id: 'hb2', title: 'Stretch' })])
    const gone = held<null>()
    m.deleteHabit.mockReturnValue(gone.promise)
    const user = setup()
    await openSheet(user)

    await user.click(await screen.findByRole('button', { name: 'Delete Read' }))
    await user.click(screen.getByRole('button', { name: 'Confirm delete Read' }))
    await waitFor(() =>
      expect(screen.queryByLabelText('Rename Read')).not.toBeInTheDocument())

    await act(async () => { gone.fail(new Error('boom')) })

    // Back, and back WHERE IT WAS: the list renders in the order the server
    // gave it, so a restored row that had moved to the end would read as a
    // second change the owner did not make.
    await waitFor(() =>
      expect(screen.getByLabelText('Rename Read')).toBeInTheDocument())
    expect([...document.querySelectorAll('.habit-name')]
      .map((n) => (n as HTMLInputElement).value)).toEqual(['Read', 'Stretch'])
  })
})


describe('<TodayView> the disk mirror, on a pinned clock', () => {
  // Friday, so the week has days behind it — the same pin, and the same reason,
  // as `<TodayView> the weekly count` above: a suite that happened to run on a
  // Monday would have nothing before `weekStartOf(today)` and the assertion
  // would pass vacuously. The zone is America/New_York, from vite.config.ts.
  const FRIDAY = new Date(2026, 7, 21, 9, 0)

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(FRIDAY)
  })
  afterEach(() => { vi.useRealTimers() })

  it('seeds the fortnight behind the habit counts as well as the day', async () => {
    // The one `api.days` read feeds the weekly counts and the "still open from
    // a recent plan" group alike. Un-seeded, both arrived a round trip after
    // the rows they belong to — the count popping in beside a habit already on
    // screen, which is the flicker the rest of the app does not have.
    setCacheUser('nick')
    const WED = '2026-08-19'
    // `[day - LOOKBACK_DAYS, day + 1)`, `to` exclusive — the window the view
    // asks for, spelled here so a cached one for any other window is a miss.
    cacheDayRange('2026-08-07', '2026-08-22', [
      plan([occurrence({ entry_id: 'h-wed', day: WED, done_at: `${WED}T09:00:00.000Z` })], WED),
    ])
    m.days.mockReturnValue(held<DayPlan[]>().promise)
    m.openDay.mockResolvedValue(plan([occurrence()]))
    setup()

    // Two occurrences: Wednesday's from the mirror, today's from the day in
    // hand — which is `MIN_WEEK_COUNT`, the point the figure starts being said.
    expect(await screen.findByText('1 of 2 this week')).toBeInTheDocument()
  })
})

describe('orderEntries', () => {
  it('reads by position, with unpositioned rows trailing', () => {
    const rows = [
      entry({ entry_id: 'c', position: null }),
      entry({ entry_id: 'b', position: 2 }),
      entry({ entry_id: 'a', position: 1 }),
    ]
    expect(orderEntries(rows).map((e) => e.entry_id)).toEqual(['a', 'b', 'c'])
  })

  it('is total, so an unchanged day never permutes between renders', () => {
    // created_at is millisecond-resolution, so a whole snapshot can share one
    // value; entry_id behind it is what stops two rows swapping places.
    const rows = [
      entry({ entry_id: 'z', position: 1, created_at: '2026-08-21T08:00:00.000Z' }),
      entry({ entry_id: 'a', position: 1, created_at: '2026-08-21T08:00:00.000Z' }),
    ]
    expect(orderEntries(rows).map((e) => e.entry_id)).toEqual(['a', 'z'])
    expect(orderEntries([...rows].reverse()).map((e) => e.entry_id)).toEqual(['a', 'z'])
  })

  it('does not mutate what it was given', () => {
    const rows = [entry({ entry_id: 'b', position: 2 }), entry({ entry_id: 'a', position: 1 })]
    orderEntries(rows)
    expect(rows.map((e) => e.entry_id)).toEqual(['b', 'a'])
  })
})

describe('weekStartOf', () => {
  it('takes the week back to Monday', () => {
    expect(weekStartOf('2026-08-21')).toBe('2026-08-17')   // Friday
    expect(weekStartOf('2026-08-17')).toBe('2026-08-17')   // Monday itself
  })

  it('puts SUNDAY at the end of its week, not the start of the next one', () => {
    // The case the whole conversion exists for: `Date.getDay()` answers 0 for
    // Sunday, so the naive subtraction leaves Sunday exactly where it is and
    // starts a fresh week on it — splitting one week's occurrences across two
    // counts, every seventh day, for anyone who looks on a Sunday.
    expect(weekStartOf('2026-08-23')).toBe('2026-08-17')
  })

  it('crosses a month and a year boundary', () => {
    expect(weekStartOf('2026-09-02')).toBe('2026-08-31')   // Wednesday
    expect(weekStartOf('2027-01-01')).toBe('2026-12-28')   // Friday
  })
})

describe('dueFromParse', () => {
  const parsed = (o: Partial<import('../daytext').ParsedEntry> = {}) =>
    ({ summary: 'gym', dueDate: '', dueTime: '', guessed: false, ...o })

  it('takes the day being planned when the line named only an hour', () => {
    expect(dueFromParse(parsed({ dueTime: '07:00' }), '2026-08-21')).toBe('2026-08-21T07:00')
  })

  it('keeps a stated date, with or without a time', () => {
    expect(dueFromParse(parsed({ dueDate: '2026-09-01' }), '2026-08-21')).toBe('2026-09-01')
    expect(dueFromParse(parsed({ dueDate: '2026-09-01', dueTime: '14:30' }), '2026-08-21'))
      .toBe('2026-09-01T14:30')
  })
})

// ── the token discipline ────────────────────────────────────────────────────

describe('the Today tab stylesheet', () => {
  const css = readFileSync(resolve(process.cwd(), 'src/styles/app.css'), 'utf8')
  const start = css.indexOf('/* today-tab:css:start */')
  const end = css.indexOf('/* today-tab:css:end */')
  const block = css.slice(start, end)

  it('is where the markers say it is', () => {
    // The two tests below assert about a slice of a file. If the markers ever
    // go missing the slice is empty and both would pass vacuously, which is
    // worse than no test at all.
    expect(start, 'the today-tab CSS start marker is gone').toBeGreaterThan(-1)
    expect(end, 'the today-tab CSS end marker is gone').toBeGreaterThan(start)
    expect(block).toContain('.today-row')
  })

  it('sizes the check-gap from the same custom property as the checkbox', () => {
    // `.today-check-gap` stands in for the checkbox on a row with nothing to
    // tick, so the two must be the same width or a mixed list loses its left
    // edge. `.check` is 17px normally and 21px under `max-width: 720px`, so a
    // gap with its own hard-coded 17px was 4px narrow on every phone.
    //
    // Asserted structurally rather than by computed style: jsdom does not apply
    // media queries, so the only thing a render test could check here is the
    // desktop case — which was never the broken one. What actually has to hold
    // is that ONE property feeds both and that neither re-declares it after the
    // override; `.today-check-gap` sits ~500 lines below the media block, so a
    // local re-declaration would win at equal specificity and restore the bug.
    expect(css).toMatch(/:root\s*\{\s*--check-size:\s*17px/)
    expect(css).toMatch(/@media[^{]*max-width:\s*720px[\s\S]*?:root\s*\{\s*--check-size:\s*21px/)
    for (const rule of ['.check', '.today-check-gap']) {
      const body = css.slice(css.indexOf(`\n${rule} {`) + 1)
      expect(body.slice(0, body.indexOf('}'))).toContain('var(--check-size)')
    }
    // Nothing may set it on a selector of its own — only :root.
    const setters = css.match(/--check-size:/g) ?? []
    expect(setters).toHaveLength(2)
  })

  it('sizes the kind column from one custom property, set only on :root', () => {
    // The same discipline as `--check-size` above, for the second structural
    // width this screen's left edge depends on. `.today-kind-mark` is the one
    // cell every row paints — a task's filled square, a note's hollow one, a
    // habit's glyph — and the whole point of it being one element of a FIXED
    // width is that a mixed list keeps a single left edge. A rule that set the
    // width on a per-kind selector instead would let one of the three drift and
    // reintroduce, kind by kind, exactly the misalignment this replaced.
    expect(css).toMatch(/:root\s*\{\s*--today-mark-w:\s*13px/)
    const body = css.slice(css.indexOf('\n.today-kind-mark {') + 1)
    expect(body.slice(0, body.indexOf('}'))).toContain('var(--today-mark-w)')
    // Only :root may set it.
    expect((css.match(/--today-mark-w:/g) ?? [])).toHaveLength(1)
    // And it is deliberately NOT a themeable token: `appearance.ts`'s allowlist
    // reaches colours, radii, families and scales, not the geometry that holds
    // a list together, so a saved theme cannot break this edge. Same reason
    // `--check-size` is absent from it too.
    const appearance = readFileSync(resolve(process.cwd(), 'src/appearance.ts'), 'utf8')
    expect(appearance).not.toContain('today-mark-w')
    expect(appearance).not.toContain('check-size')
  })

  it('gives the habits group a surface of its own, and never only that', () => {
    // What tells a habit from a task on this tab is three carriers, and the
    // point of the test is that no one of them is load-bearing alone:
    //
    //  * the BAND — `.today-habits` paints --paper, the recessed tone the
    //    sidebar and a dimmed calendar cell already use for "beside the
    //    content, not part of it". It is the one a reader sees mid-scroll,
    //    and it is the one a theme can erase: --paper is themeable, and an
    //    appearance that sets it to --bg flattens the group back to nothing.
    //  * the MARK — the ↻ on every habit row, which survives that, and a
    //    greyscale screenshot, and being read one row at a time.
    //  * the HEADINGS above and below it, which survive all of that and are
    //    the only carrier that says anything to a screen reader.
    //
    // Asserted here rather than by computed style because jsdom applies no
    // stylesheet to a render, so the rules themselves are the only thing a
    // test in this file can see.
    expect(block).toMatch(/\.today-habits\s*\{[^}]*background:\s*var\(--paper\)/)
    // The band's own hover, computed FROM the band. `.today-row:hover` paints
    // --bg-elev, which is a step lighter than --bg in the light themes and — 
    // because --paper is lighter than --bg-elev in the dark ones — a step
    // DARKER than the band here, so a habit row receded on hover while every
    // other row on the screen lifted.
    expect(block).toMatch(/\.today-habits\s+\.today-row:hover\s*\{[^}]*--paper/)
    // The mark carries its own weight rather than the column's furniture
    // colour: --fg-faint is the quietest token in every theme, and it is the
    // wrong one for the single character that says which kind a row is. Filled
    // against hollow is a comparison needing both marks on screen; the glyph
    // has to be legible on its own.
    expect(block)
      .toMatch(/\[data-kind="habit"\]\s*\{[^}]*color:\s*var\(--fg-muted\)/)
    // Colour ONLY. `.dash-day-row .today-kind-mark` sets a smaller font-size
    // for the dashboard's day module and carries the same specificity as this
    // selector, so a size here would win on source order and silently undo it
    // — on the one list in the app where habits and tasks are interleaved with
    // no band and no heading to help.
    const rule = block.slice(block.indexOf('.today-kind-mark[data-kind="habit"]'))
    expect(rule.slice(0, rule.indexOf('}'))).not.toContain('font-size')
  })

  it('contains no literal colour', () => {
    // The appearance/token system is the point: a rule written in hex looks
    // right in the shipped theme and is wrong — often invisible — under a
    // custom or preset one, and nothing about the shipped look gives it away.
    const literals = block.match(/#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(|\boklab\(/g)
    expect(literals ?? []).toEqual([])
  })

  it('resolves every colour-bearing declaration through a token', () => {
    // The stronger half: `color: red` carries no hex and no function, and would
    // sail past the check above while being just as unreachable by a theme.
    const DECL = /\b(color|background|background-color|border|border-top|border-bottom|border-left|border-right|outline|box-shadow|fill|stroke)\s*:\s*([^;}]+)/g
    const KEYWORD = /^(none|transparent|inherit|currentcolor|unset|initial|0)$/i
    const offenders: string[] = []
    for (const [, prop, raw] of block.matchAll(DECL)) {
      const value = raw.trim()
      if (value.includes('var(--') || KEYWORD.test(value)) continue
      offenders.push(`${prop}: ${value}`)
    }
    expect(offenders).toEqual([])
  })
})

describe('Start working', () => {
  it('is offered on today, in the planning mode, when there is somewhere to go', async () => {
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    const onStart = vi.fn()
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TodayView rev={0} onExpire={vi.fn()} onStartWorking={onStart} />
      </DataProvider>,
    )
    await screen.findByText('Water the plants')
    await userEvent.click(screen.getByRole('button', { name: 'Start working' }))
    expect(onStart).toHaveBeenCalledTimes(1)
    // Not in a review: a record is not something to start.
    await userEvent.click(screen.getByRole('button', { name: 'Review' }))
    expect(screen.queryByRole('button', { name: 'Start working' })).not.toBeInTheDocument()
  })

  it('is absent on a day that has happened, and absent without a way in', async () => {
    m.day.mockImplementation(async (d) => plan([entry({ day: d, title: 'Yesterday' })], d))
    const user = setup()   // no `onStartWorking`
    expect(screen.queryByRole('button', { name: 'Start working' })).not.toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Previous day' }))
    await screen.findByText('Yesterday')
    expect(screen.queryByRole('button', { name: 'Start working' })).not.toBeInTheDocument()
  })
})

describe('what was worked', () => {
  it('shows beside the estimate in a review, and nowhere on the live list', async () => {
    m.openDay.mockResolvedValue(plan([
      entry({ title: 'Water the plants', estimate_minutes: 25, worked_seconds: 31 * 60 }),
      entry({ entry_id: 'e2', title: 'Invoice', position: 2 }),
    ]))
    const user = setup()
    await screen.findByText('Water the plants')
    expect(screen.queryByText('31m')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Review' }))
    expect(await screen.findByText('31m')).toBeInTheDocument()
    expect(screen.getByTitle('31m worked')).toBeInTheDocument()
    // A row never worked keeps its (empty) cell, so the column holds.
    const cells = document.querySelectorAll('.today-worked')
    expect(cells).toHaveLength(2)
  })
})
