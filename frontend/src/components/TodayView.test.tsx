import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TodayView, dueFromParse, orderEntries } from './TodayView'
import { DataProvider } from '../data'
import { setCacheUser } from '../cache'
import { api, type DayEntry, type DayPlan, type List, type Task } from '../api'

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
  done_at: null, dropped_at: null, created_at: '2026-08-21T08:00:00.000Z', ...o,
})

const plan = (entries: DayEntry[] = [], day = today()): DayPlan =>
  ({ day, planned: true, entries })

function setup() {
  render(
    <DataProvider rev={0} onExpire={vi.fn()}>
      <TodayView rev={0} onExpire={vi.fn()} />
    </DataProvider>,
  )
  return userEvent.setup()
}

/** The day's own rows (not the suggestion lists, which reuse the row class). */
const dayRows = () => [...document.querySelectorAll('.today-row:not(.today-sug)')]
const rowTitles = () =>
  dayRows().map((r) => r.querySelector('.today-title')?.textContent ?? '')

beforeEach(() => {
  vi.clearAllMocks()
  setCacheUser('')
  localStorage.clear()
  m.lists.mockResolvedValue([list])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.openDay.mockResolvedValue(plan())
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

    const chip = await screen.findByRole('status')
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

  it('dismissing the reading commits the literal line instead', async () => {
    const user = setup()
    await user.type(screen.getByLabelText('Add to today'), 'gym at 7')
    await user.click(await screen.findByRole('button', { name: /as typed/i }))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

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
