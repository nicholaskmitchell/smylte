/**
 * The 2026-09-03 sweep — the Today tab (group fe-b1).
 *
 * Six findings, all on the one surface, and two threads run through them.
 * **Three are a closed finding's fix covering only the arm it was found on**:
 * the #60 "Couldn't read today" line lives in the planning arm and a past day
 * never takes that arm; the #68 decided-counter lives in the open dialog and
 * dies with it; the #59 unmount-commit went to the two ritual fields and not
 * to the habit rename, which has the identical shape. **Two are the add box
 * putting a FAILED line back carelessly** — without the kind the owner pinned
 * to it, and over whatever they have typed since. The last is arithmetic: the
 * calendar figure charges a multi-day event's whole span to every day it
 * touches.
 *
 * Every pin was written first and run red against the code as it stood; the
 * failing assertion is quoted in the coordinator's report. Each drives the real
 * `TodayView` under the same api mock `TodayView.test.tsx` uses, and the
 * fixtures are copied from there field for field rather than imported, so this
 * file reads on its own. Where a finding's copy is a choice (the past-day error
 * line, the shutdown's "nothing left" hint) the assertion names the OUTCOME —
 * an operable retry, the absence of the false sentence — and a control beside
 * it keeps the healthy path honest.
 *
 * The suite runs pinned to America/New_York (vite.config.ts); the multi-day
 * event pin builds its dates from the clock, so it holds in any zone.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { DataProvider } from './data'
import { setCacheUser } from './cache'
import { I18nProvider } from './i18n'
import { TodayView } from './components/TodayView'
import { api, type CalEvent, type DayEntry, type DayPlan, type Habit, type List,
  type Task } from './api'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)

// ── fixtures (TodayView.test.tsx's, field for field) ─────────────────────────

const pad = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
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
  completed: false, cancelled: false, parked: false, parked_at: null,
  priority: null, priority_label: 'none',
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

const habit = (o: Partial<Habit> = {}): Habit => ({
  id: 'hb1', title: 'Read', days: '', paused_at: null, position: 1,
  estimate_minutes: null, created_at: '2026-08-01T08:00:00.000Z', ...o,
})

const calEvent = (o: Partial<CalEvent> = {}): CalEvent => ({
  uid: 'ev1', id: 'ev1', recurrence_id: null, is_recurring: false, calendar: '/c1/',
  summary: 'Standup', description: null, location: null,
  start: `${today()}T09:00:00`, start_is_date: false,
  end: `${today()}T10:30:00`, end_is_date: false, duration: null,
  all_day: false, status: null, busy: true, notify_minutes_before: null, tags: [], has_rrule: false,
  href: '/c1/ev1.ics', etag: '"1"', ...o,
})

const plan = (entries: DayEntry[] = [], day = today(), o: Partial<DayPlan> = {}): DayPlan => ({
  day, planned: true, entries,
  capacity_minutes: null, capacity: null,
  committed_at: null, committed_over_minutes: null, shutdown_at: null, reflection: null, ...o,
})
const withCapacity = (entries: DayEntry[], capacity: number) =>
  plan(entries, today(), { capacity, capacity_minutes: capacity })

/** A promise left in flight, and the functions that land or fail it. */
const held = <T,>() => {
  let land: (v: T) => void = () => {}
  let fail: (e: unknown) => void = () => {}
  const promise = new Promise<T>((res, rej) => { land = res; fail = rej })
  return { promise, land: (v: T) => land(v), fail: (e: unknown) => fail(e) }
}

function setup(lang: 'en' | 'de' = 'en') {
  render(
    <I18nProvider value={lang}>
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TodayView rev={0} onExpire={vi.fn()} />
      </DataProvider>
    </I18nProvider>,
  )
  return userEvent.setup()
}

const fateChip = () => document.getElementById('today-add-fate')

beforeEach(() => {
  vi.clearAllMocks()
  setCacheUser('')
  localStorage.clear()
  m.lists.mockResolvedValue([list])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.openDay.mockResolvedValue(plan())
  m.day.mockImplementation(async (d) => plan([], d))
  m.days.mockResolvedValue([])
  m.habits.mockResolvedValue([])
  m.patchHabit.mockImplementation(async (id, body) => habit({
    id,
    ...(body.title !== undefined ? { title: body.title } : {}),
    ...(body.days !== undefined ? { days: body.days } : {}),
    paused_at: body.paused ? '2026-08-21T10:00:00.000Z' : null,
  }))
  m.deleteHabit.mockResolvedValue(null)
  m.patchDayEntry.mockImplementation(async (_d, id) => entry({ entry_id: id }))
  m.rollDayEntry.mockImplementation(async (_d, id, to) =>
    entry({ entry_id: id, rolled_to: to }))
  m.addDayEntry.mockImplementation(async (d, body) => entry({
    entry_id: body.entry_id, day: d, kind: body.kind,
    list: body.list ?? null, uid: body.uid ?? null, title: body.title ?? null,
    position: 9,
  }))
  // `createTask`'s body is `Record<string, unknown>` on the api, so the two
  // fields are narrowed here rather than trusted.
  m.createTask.mockImplementation(async (l, body) => task({
    uid: 'created@tasksd', list: l,
    summary: typeof body.summary === 'string' ? body.summary : '',
    due: typeof body.due === 'string' ? body.due : null,
  }))
})

// ═══════════════════════════════════════════════════════════════════════════
// The add box on a FAILED add
// ═══════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — the add box after a failed add', () => {
  // ── TodayView.tsx:1503 — the pin is dropped on a failed add, so the retry
  //    silently authors the OTHER kind ─────────────────────────────────────
  it('keeps a pinned NOTE a note when the line comes back and is retried', async () => {
    // EVIDENCE. `commit()` does `setText(''); setPinned(null)` before the write
    // and restores only the TEXT on failure, so `willBe` re-reads the retried
    // line from the parser alone: "call mum at 6" pinned as a note comes back
    // as a task, and the second Enter authors a real VTODO with a DUE onto the
    // CalDAV list — the exact thing the owner pressed "Make it a note" to
    // refuse. The chip flips too, but it is advisory ("never a gate") and a
    // blind retry lands the wrong kind.
    m.addDayEntry.mockRejectedValueOnce(new Error('nope'))
    const user = setup()
    const box = await screen.findByLabelText('Add to today')
    await user.type(box, 'call mum at 6')
    await user.click(await screen.findByRole('button', { name: 'Make it a note' }))
    await user.type(box, '{Enter}')
    await waitFor(() => expect(box).toHaveValue('call mum at 6'))

    // The intent survives the failure with the line it was about.
    expect(fateChip()?.textContent).toMatch(/Note/)
    await user.type(box, '{Enter}')
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalledTimes(2))

    expect(m.createTask).not.toHaveBeenCalled()
    expect(m.addDayEntry.mock.calls[1][1]).toMatchObject({ kind: 'note', title: 'call mum at 6' })
  })

  it('keeps a pinned TASK a task, and finishes the same write on the retry', async () => {
    // The other direction, and the one that leaves data behind: an undated line
    // pinned as a task whose CREATE landed and whose day write failed came back
    // as a note, so the retry wrote `{kind: 'note'}` and the VTODO already on
    // the list was pointed at by no day — `retry.current.task` was never read
    // because `addNote` was taken instead.
    m.addDayEntry.mockRejectedValueOnce(new Error('nope'))
    const user = setup()
    const box = await screen.findByLabelText('Add to today')
    await user.type(box, 'call mum')
    await user.click(await screen.findByRole('button', { name: 'Make it a task' }))
    await user.type(box, '{Enter}')
    await waitFor(() => expect(box).toHaveValue('call mum'))

    expect(fateChip()?.textContent).toMatch(/Task/)
    await user.type(box, '{Enter}')
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalledTimes(2))

    // One create, and the retry points the day at THAT task.
    expect(m.createTask).toHaveBeenCalledTimes(1)
    expect(m.addDayEntry.mock.calls[1][1]).toMatchObject({ kind: 'task', uid: 'created@tasksd' })
  })

  // ── TodayView.tsx:1503 — the failed line is put back OVER what the owner
  //    has typed since ────────────────────────────────────────────────────────
  it('does not overwrite the next line being typed with the one that failed', async () => {
    // EVIDENCE. `if (!ok) setText(raw)` is unconditional. The box clears on the
    // press so the next line can be typed while the round trip is out — "the
    // whole bargain of a frictionless add" — and a slow rejection then lands
    // the OLD line over the half-typed new one. The habits sheet's add box in
    // the same file already guards this (`setTitle((cur) => cur || t)`); this
    // box did not.
    const add = held<DayEntry>()
    m.addDayEntry.mockReturnValueOnce(add.promise)
    const user = setup()
    const box = await screen.findByLabelText('Add to today')
    await user.type(box, 'call mum{Enter}')
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalledTimes(1))
    await user.type(box, 'ring the bank')

    add.fail(new Error('nope'))
    // Give the rejection every chance to land its (wrong) write.
    await waitFor(() => expect(
      [...document.querySelectorAll('.today-row')].some((r) => r.textContent?.includes('call mum')),
    ).toBe(false))
    expect(box).toHaveValue('ring the bank')
  })

  // CONTROL. A failed line still comes back into an EMPTY box, pin and all —
  // the over-correction for the pin above is to stop restoring anything.
  it('still gives a failed line back to an empty box', async () => {
    m.addDayEntry.mockRejectedValueOnce(new Error('nope'))
    const user = setup()
    const box = await screen.findByLabelText('Add to today')
    await user.type(box, 'call mum{Enter}')
    await waitFor(() => expect(box).toHaveValue('call mum'))
  })

  // CONTROL. A SUCCESSFUL commit still forgets the pin — the next dated line
  // reads as a task again. Restoring the pin unconditionally would fail this.
  it('still forgets the pin once the line lands', async () => {
    const user = setup()
    const box = await screen.findByLabelText('Add to today')
    await user.type(box, 'gym at 7')
    await user.click(await screen.findByRole('button', { name: 'Make it a note' }))
    await user.type(box, '{Enter}')
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalled())

    await user.type(box, 'gym at 8')
    await waitFor(() => expect(fateChip()?.textContent).toMatch(/Task/))
  })
})

// ═══════════════════════════════════════════════════════════════════════════
// A failed read of a PAST day, or of today in Review
// ═══════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — a failed read on the look-back arm', () => {
  // ── TodayView.tsx:2605 — the #60 error line + retry render only inside the
  //    `!reviewing` arm; a past day always takes the other one ──────────────
  it('says a past day could not be read, and offers a retry that re-reads it', async () => {
    // EVIDENCE. `dayError` is set for every day (the read effect's failure arm
    // covers `api.day` too), but the paragraph that shows it sits inside
    // `{!reviewing ? (…) : <LookBack/>}`, and `reviewing = !isToday || …`. On a
    // past day `LookBack` gets `review === null` and returns null, so a 502 on
    // GET /api/day/{yesterday} paints "Look back", the nav and the date over an
    // empty `.scroll` — no error, no retry, and the guard toast the only
    // signal. Measured: `Try again` absent, `.scroll` textContent "".
    m.day.mockRejectedValue(new Error('502'))
    const user = setup()
    await screen.findByLabelText('Add to today')
    await user.click(screen.getByRole('button', { name: 'Previous day' }))
    await waitFor(() => expect(m.day).toHaveBeenCalledTimes(1))

    const retry = await screen.findByRole('button', { name: 'Try again' })
    // Not "Couldn't read TODAY" under a heading that says "Look back".
    expect(retry.closest('[role="status"]')?.textContent).not.toMatch(/today/i)
    await user.click(retry)
    await waitFor(() => expect(m.day).toHaveBeenCalledTimes(2))
    expect(m.day.mock.calls[1][0]).toBe(inDays(-1))
  })

  it('keeps the error and the retry when today is switched to Review', async () => {
    m.openDay.mockRejectedValue(new Error('boom'))
    const user = setup()
    await screen.findByLabelText('Add to today')
    await screen.findByRole('button', { name: 'Try again' })

    await user.click(screen.getByRole('button', { name: 'Review' }))

    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  // CONTROL. A past day that reads fine still shows its record and no error.
  it('still shows a past day that reads', async () => {
    m.day.mockImplementation(async (d) =>
      plan([entry({ entry_id: 'y', day: d, title: 'Back then' })], d))
    const user = setup()
    await screen.findByLabelText('Add to today')
    await user.click(screen.getByRole('button', { name: 'Previous day' }))

    expect(await screen.findByText('Back then')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })
})

// ═══════════════════════════════════════════════════════════════════════════
// The calendar-partial banner, in German
// ═══════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — the calendar-partial banner', () => {
  // ── TodayView.tsx:2316 — hardcoded English beside a comment that says
  //    "same banner, same words, as HomeView" ────────────────────────────────
  it('speaks the account\'s language, through the key HomeView uses', async () => {
    // EVIDENCE. HomeView renders `tr('home.calPartial', { cals })`, and both
    // catalogues carry the key; TodayView's twin is a JSX literal. A German
    // account with one calendar 502ing saw "Couldn’t load Privat — some events
    // may be missing." in the middle of a German tab. The English render is
    // byte-identical either way, so the existing English test cannot see it.
    m.calendars.mockResolvedValue([cal])
    m.events.mockRejectedValue(new Error('502'))
    setup('de')

    await waitFor(() => expect(document.querySelector('.cal-partial')).not.toBeNull())
    const banner = document.querySelector('.cal-partial')!
    expect(banner).toHaveTextContent('Personal konnte nicht geladen werden')
    expect(banner.textContent).not.toMatch(/Couldn/)
  })
})

// ═══════════════════════════════════════════════════════════════════════════
// The calendar figure beside the capacity
// ═══════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — minutes of calendar on THIS day', () => {
  const loadCal = () => document.querySelector('.today-load-cal')?.textContent ?? ''

  // ── TodayView.tsx:1999 — `meetingMinutes` sums the whole span of every
  //    event the day touches ─────────────────────────────────────────────────
  it('charges a three-day event only the 24 hours that fall on today', async () => {
    // EVIDENCE. `todaysEvents` comes from `bucketByDay`, which lists a span on
    // every day it covers with the original start/end intact on continuation
    // rows; `meetingMinutes` then sums `end - start` of the whole event. One
    // timed event from yesterday 09:00 to tomorrow 17:00 rendered " · 56h on
    // the calendar" beside a 5h capacity, and the planning ritual said "You
    // already have 56h on the calendar today." The memo's own docstring says
    // "Minutes of calendar on this day".
    m.calendars.mockResolvedValue([cal])
    m.events.mockResolvedValue([calEvent({
      summary: 'Offsite', start: `${inDays(-1)}T09:00:00`, end: `${inDays(1)}T17:00:00`,
    })])
    m.openDay.mockResolvedValue(withCapacity([entry({ title: 'One', estimate_minutes: 60 })], 300))
    setup()
    await screen.findByText('One')

    await waitFor(() => expect(loadCal()).toMatch(/on the calendar/))
    expect(loadCal()).toMatch(/\b24h on the calendar/)
  })

  it('charges an overnight event only the hours before midnight', async () => {
    m.calendars.mockResolvedValue([cal])
    m.events.mockResolvedValue([calEvent({
      summary: 'On call', start: `${today()}T22:00:00`, end: `${inDays(1)}T02:00:00`,
    })])
    m.openDay.mockResolvedValue(withCapacity([entry({ title: 'One', estimate_minutes: 60 })], 300))
    setup()
    await screen.findByText('One')

    await waitFor(() => expect(loadCal()).toMatch(/on the calendar/))
    expect(loadCal()).toMatch(/\b2h on the calendar/)
  })

  // CONTROL. A same-day event is still counted in full.
  it('still counts a same-day event in full', async () => {
    m.calendars.mockResolvedValue([cal])
    m.events.mockResolvedValue([calEvent()])
    m.openDay.mockResolvedValue(withCapacity([entry({ title: 'One', estimate_minutes: 60 })], 300))
    setup()
    await screen.findByText('One')

    await waitFor(() => expect(loadCal()).toMatch(/1h 30m on the calendar/))
  })
})

// ═══════════════════════════════════════════════════════════════════════════
// The shutdown ritual, re-opened
// ═══════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — the shutdown ritual after the owner came back', () => {
  const DONE_SENTENCE = 'Everything on today is done. Nothing to carry.'
  const NOTHING_AT_ALL = 'Nothing on today, and nothing finished off-plan.'

  const open = async (user: ReturnType<typeof setup>) => {
    await user.click(await screen.findByRole('button', { name: 'Shut down' }))
    return screen.findByRole('dialog', { name: 'Shut down the day' })
  }
  const body = (dialog: HTMLElement) => dialog.querySelector('.plan-body')?.textContent?.trim() ?? ''

  // ── ShutdownRitual.tsx:101 — the #68 counter lives in the open dialog ─────
  it('still knows the day was postponed after the dialog was closed and re-opened', async () => {
    // EVIDENCE. #68 was fixed with `const [decided, setDecided] = useState(0)`
    // in `ShutdownRitual`, which survives Back/Next and nothing else: TodayView
    // renders the ritual only while `shutdown` is true, so Close unmounts it and
    // the count dies. The stamps that tell "moved" from "done" apart —
    // `rolled_to` / `dropped_at` — are on `allEntries` and are never handed in.
    // Measured: move all 2, Close, Shut down again -> step 1 "0 of 0 done
    // Nothing on today, and nothing finished off-plan.", step 2 the exact
    // sentence #68's pin forbids. `DoneStep`'s own comment says coming back is
    // "allowed and expected".
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'a', title: 'Alpha', position: 1 }),
      entry({ entry_id: 'b', title: 'Bravo', position: 2 }),
    ]))
    const user = setup()
    let dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(within(dialog).getByRole('button', { name: /Move all 2 to tomorrow/ }))
    await waitFor(() => expect(m.rollDayEntry).toHaveBeenCalledTimes(2))

    await user.click(within(dialog).getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(
      screen.queryByRole('dialog', { name: 'Shut down the day' })).not.toBeInTheDocument())
    dialog = await open(user)

    // Step one: the day was not a day with nothing on it.
    expect(body(dialog), 'step one calls a postponed day an empty one').not.toContain(NOTHING_AT_ALL)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    expect(body(dialog), 'step two calls a postponed day a finished one').not.toBe(DONE_SENTENCE)
  })

  it('reads the decision off the record on a fresh mount', async () => {
    // Stronger than the re-open: a reload (or a tab switch, which unmounts
    // TodayView) with the rows already stamped on the wire. No session state is
    // involved — the ritual simply never read the stamps it was not given.
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'a', title: 'Alpha', position: 1, rolled_to: inDays(1) }),
      entry({ entry_id: 'b', title: 'Bravo', position: 2, dropped_at: '2026-08-21T20:00:00.000Z' }),
    ]))
    const user = setup()
    const dialog = await open(user)

    expect(body(dialog)).not.toContain(NOTHING_AT_ALL)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    expect(body(dialog)).not.toBe(DONE_SENTENCE)
  })

  // CONTROL. A day that never had anything on it, and nothing decided about,
  // still says so — the over-correction is to never print the empty state.
  it('still says nothing at all when there was nothing at all', async () => {
    const user = setup()
    const dialog = await open(user)
    expect(body(dialog)).toContain(NOTHING_AT_ALL)
  })

  // CONTROL. A day whose one row was ticked still gets the done sentence.
  it('still says everything is done when everything was done', async () => {
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'a', title: 'Alpha', position: 1, done_at: '2026-08-21T17:00:00.000Z' }),
    ]))
    const user = setup()
    const dialog = await open(user)
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    expect(body(dialog)).toBe(DONE_SENTENCE)
  })
})

// ═══════════════════════════════════════════════════════════════════════════
// A habit rename closed with Escape
// ═══════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — a habit rename closed with Escape', () => {
  const openSheet = async (user: ReturnType<typeof setup>) => {
    await user.click(await screen.findByRole('button', { name: 'Habits' }))
    return screen.findByRole('dialog', { name: 'Habits' })
  }

  // ── TodayView.tsx:3635 — the name field commits on blur and Enter only, and
  //    Escape unmounts it without a blur ─────────────────────────────────────
  it('keeps a rename the owner closed with Escape', async () => {
    // EVIDENCE. `HabitsSheet` binds `useEscape(onClose)` on the window and
    // Escape unmounts the whole sheet; browsers fire no blur for a focused
    // element removed from the DOM, so the typed name is never sent. #59
    // established the rule — Escape must not throw away blur-committed text —
    // and added unmount-commit effects to `ReflectStep` and `CapacityStep`;
    // this is the third such field. Measured: clear "Read", type "Read more",
    // Escape -> `api.patchHabit` calls `[]`. The ✕ and the scrim are safe for
    // the reason they were there: their mousedown blurs first.
    m.habits.mockResolvedValue([habit()])
    const user = setup()
    await openSheet(user)
    const name = await screen.findByLabelText('Rename Read')
    await user.clear(name)
    await user.type(name, 'Read more')

    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Habits' })).not.toBeInTheDocument())

    await waitFor(() =>
      expect(m.patchHabit).toHaveBeenCalledWith('hb1', { title: 'Read more' }))
  })

  // CONTROL. The ordinary path — type, tab away, Escape — sends ONE patch, not
  // a second copy of the same title from the unmount.
  it('does not send a rename twice when it was already committed on blur', async () => {
    m.habits.mockResolvedValue([habit()])
    const user = setup()
    await openSheet(user)
    const name = await screen.findByLabelText('Rename Read')
    await user.clear(name)
    await user.type(name, 'Read more')
    await user.tab()
    await waitFor(() =>
      expect(m.patchHabit).toHaveBeenCalledWith('hb1', { title: 'Read more' }))

    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Habits' })).not.toBeInTheDocument())

    expect(m.patchHabit).toHaveBeenCalledTimes(1)
  })

  // CONTROL. An untouched field, or one merely cleared, sends nothing on the
  // way out: an empty title is a 422 and a blur snaps it back rather than
  // raising one.
  it('sends nothing for a name that was only cleared', async () => {
    m.habits.mockResolvedValue([habit()])
    const user = setup()
    await openSheet(user)
    const name = await screen.findByLabelText('Rename Read')
    await user.clear(name)

    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Habits' })).not.toBeInTheDocument())

    expect(m.patchHabit).not.toHaveBeenCalled()
  })
})
