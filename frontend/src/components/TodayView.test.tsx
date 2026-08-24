import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TodayView, dueFromParse, orderEntries, weekStartOf } from './TodayView'
import { DataProvider } from '../data'
import { setCacheUser } from '../cache'
import {
  api,
  type DayEntry, type DayEntrySource, type DayPlan, type Habit, type List, type Task,
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
  completed_at: null, kanban_column: null, has_rrule: false,
  created: null, last_modified: null,
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

const entry = (o: Partial<DayEntry> = {}): DayEntry => ({
  entry_id: 'e1', day: today(), kind: 'note', list: null, uid: null,
  title: 'Water the plants', source: 'user', position: 1,
  done_at: null, dropped_at: null, habit_id: null,
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
  created_at: '2026-08-01T08:00:00.000Z', ...o,
})

const plan = (entries: DayEntry[] = [], day = today()): DayPlan =>
  ({ day, planned: true, entries })

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

// ── arranging the day ───────────────────────────────────────────────────────

describe('<TodayView> arranging the day', () => {
  /** Three rows at positions 1, 2, 3 — A, B, C top to bottom. */
  const abc = () => plan([
    entry({ entry_id: 'a', title: 'Alpha', position: 1 }),
    entry({ entry_id: 'b', title: 'Bravo', position: 2 }),
    entry({ entry_id: 'c', title: 'Charlie', position: 3 }),
  ])

  /** Drag the row titled `from` onto the row titled `to`. */
  const dragOnto = (from: string, to: string) => {
    const row = (t: string) =>
      dayRows().find((r) => r.querySelector('.today-title')?.textContent === t)!
    fireEvent.dragStart(row(from))
    fireEvent.dragOver(row(to))
    fireEvent.drop(row(to))
  }

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

    const mark = document.querySelector('.today-kind-mark')
    expect(mark).toHaveClass('task')
    expect((mark as HTMLElement).style.background).toBe('')
  })

  it('wears the list colour when there is one', async () => {
    m.tasks.mockResolvedValue([task()])
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'e-task', kind: 'task', list: 'l1', uid: 'u1', title: null }),
    ]))
    setup()
    await screen.findByText('Ship it')

    expect((document.querySelector('.today-kind-mark') as HTMLElement).style.background)
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
    expect(sug.querySelectorAll('.today-kind-mark.task')).toHaveLength(1)
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
