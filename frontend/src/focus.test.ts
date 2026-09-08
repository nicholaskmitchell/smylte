import { describe, expect, it } from 'vitest'
import {
  AWAY_GRACE_S, DEFAULT_FOCUS, capReached, clockOf, currentFinished, elapsedIn, isCapped,
  nextPhase, queueOf, sanitizeFocusSettings, wasAway, workedNow,
} from './focus'
import type { DayEntry, FocusSession, Task } from './api'

const T0 = Date.parse('2026-09-03T09:00:00.000Z')
const at = (seconds: number) => T0 + seconds * 1000
const iso = (ms: number) => new Date(ms).toISOString()

const session = (o: Partial<FocusSession> = {}): FocusSession => ({
  day: '2026-09-03', phase: 'focus', phase_length_s: 1500, phase_elapsed_s: 0,
  running_since: iso(T0), intervals_done: 0, entry_id: 'n1', passed: [],
  started_at: iso(T0), ended_at: null, updated_at: iso(T0), ...o,
})

const entry = (o: Partial<DayEntry> = {}): DayEntry => ({
  entry_id: 'n1', day: '2026-09-03', kind: 'note', list: null, uid: null,
  title: 'Memo', source: 'user', position: 1,
  done_at: null, dropped_at: null, habit_id: null, rolled_to: null,
  estimate_minutes: null, worked_seconds: null, capped: null,
  created_at: '2026-09-03T08:00:00.000Z', ...o,
})

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, parked: false, parked_at: null,
  priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [], parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null, completed_at: null,
  kanban_column: null, estimated_minutes: null, notify_minutes_before: null,
  has_rrule: false, created: null, last_modified: null,
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

describe('the clock', () => {
  it('counts the live run and clamps it to what the phase has left', () => {
    // THE CLAMP: ten minutes in reads ten minutes; eight hours in reads the
    // one interval the phase was, never the night.
    expect(elapsedIn(session(), at(600))).toBe(600)
    expect(elapsedIn(session(), at(8 * 3600))).toBe(1500)
    // Banked time counts from the anchor onwards, and a paused session — no
    // anchor — reads its banked figure whatever the clock says.
    expect(elapsedIn(session({ phase_elapsed_s: 900 }), at(300))).toBe(1200)
    expect(elapsedIn(session({ phase_elapsed_s: 600, running_since: null }), at(99_999))).toBe(600)
  })

  it('says whether the number on screen is moving', () => {
    expect(clockOf(session(), at(600))).toMatchObject(
      { remaining: 900, running: true, over: false, paused: false })
    expect(clockOf(session(), at(1500))).toMatchObject({ remaining: 0, over: true, running: false })
    expect(clockOf(session({ running_since: null }), at(0))).toMatchObject(
      { paused: true, running: false, over: false })
    expect(clockOf(session({ ended_at: iso(T0) }), at(0))).toMatchObject(
      { running: false, paused: false })
  })

  it('knows the difference between late and away', () => {
    // Twenty seconds past the end in a throttled tab: over, not abandoned.
    expect(wasAway(session(), at(1520))).toBe(false)
    expect(wasAway(session(), at(1500 + AWAY_GRACE_S + 1))).toBe(true)
    // A paused session was left on purpose; an ended one is a record.
    expect(wasAway(session({ running_since: null }), at(99_999))).toBe(false)
    expect(wasAway(session({ ended_at: iso(T0) }), at(99_999))).toBe(false)
    // The overshoot is measured against what the phase had LEFT.
    expect(wasAway(session({ phase_elapsed_s: 1400 }), at(100 + AWAY_GRACE_S + 1))).toBe(true)
  })
})

describe('the cap', () => {
  const memo = entry({ estimate_minutes: 25, worked_seconds: 1470 })

  it('fires when the live run carries the row past its estimate', () => {
    // 24:30 banked plus forty seconds of this phase = past 25 minutes.
    expect(workedNow(memo, session(), at(40))).toBe(1510)
    expect(capReached({ ...memo, capped: true }, session(), at(40), false)).toBe(true)
    expect(capReached({ ...memo, capped: true }, session(), at(20), false)).toBe(false)
  })

  it('never fires for a row that runs until done, or has nothing to stop at', () => {
    expect(capReached({ ...memo, capped: false }, session(), at(8 * 3600), true)).toBe(false)
    expect(isCapped(entry({ estimate_minutes: null, capped: true }), true)).toBe(false)
    // Not said follows the account's default, either way.
    expect(isCapped(memo, true)).toBe(true)
    expect(isCapped(memo, false)).toBe(false)
  })

  it('credits the live run only to the row being worked, in a focus phase', () => {
    expect(workedNow(memo, session({ entry_id: 'other' }), at(40))).toBe(1470)
    expect(workedNow(memo, session({ phase: 'break' }), at(40))).toBe(1470)
    expect(workedNow(memo, null, at(40))).toBe(1470)
    expect(workedNow(entry(), session(), at(40))).toBe(40)
  })
})

describe('the next phase', () => {
  const settings = { ...DEFAULT_FOCUS, longEvery: 4, brk: 3, longBrk: 9 }

  it('walks the cadence the server does', () => {
    const first = nextPhase(session(), settings, false, at(1500))
    expect(first).toMatchObject(
      { phase: 'break', intervals_done: 1, phase_length_s: 180, phase_elapsed_s: 0 })
    expect(first.running_since).toBe(iso(at(1500)))
    expect(nextPhase(first, settings, false, at(0))).toMatchObject(
      { phase: 'focus', intervals_done: 1, phase_length_s: 1500 })
    // The fourth interval done is the long one; with 0 there never is one.
    const third = session({ intervals_done: 3 })
    expect(nextPhase(third, settings, false, at(0))).toMatchObject(
      { phase: 'long_break', intervals_done: 4, phase_length_s: 540 })
    expect(nextPhase(third, { ...settings, longEvery: 0 }, false, at(0)).phase).toBe('break')
  })

  it('"keep going" skips the break without un-counting the interval', () => {
    expect(nextPhase(session(), settings, true, at(0))).toMatchObject(
      { phase: 'focus', intervals_done: 1, phase_length_s: 1500 })
  })
})

describe('the queue', () => {
  const rows = [
    entry({ entry_id: 'n1', position: 1 }),
    entry({ entry_id: 't2', kind: 'task', list: 'l1', uid: 'u1', title: null, position: 2 }),
    entry({ entry_id: 'h1', kind: 'habit', source: 'habit', habit_id: 'hb', position: null }),
    entry({ entry_id: 'n3', position: 3, done_at: '2026-09-03T08:30:00.000Z' }),
    entry({ entry_id: 'n4', position: 4, dropped_at: '2026-09-03T08:30:00.000Z' }),
    entry({ entry_id: 'n5', position: 5 }),
    entry({ entry_id: 'n6', position: 6, rolled_to: '2026-09-04' }),
  ]

  it('is the plan order with habits first, and paints what the server named', () => {
    const q = queueOf(rows, [task()], true, session({ entry_id: 't2', passed: ['n5'] }))
    expect(q.current?.entry_id).toBe('t2')
    // Behind the current row the habit comes first, however the column sorts it.
    expect(q.next?.entry_id).toBe('h1')
    expect(q.open.map((e) => e.entry_id)).toEqual(['t2', 'h1', 'n1'])
    expect(q.remaining).toBe(1)
    // Done, dropped, rolled and set-aside rows are not on it.
    for (const gone of ['n3', 'n4', 'n5', 'n6']) {
      expect(q.open.some((e) => e.entry_id === gone)).toBe(false)
    }
  })

  it('never elects a current row of its own', () => {
    const q = queueOf(rows, [task()], true, session({ entry_id: null }))
    expect(q.current).toBeNull()
    expect(q.next).toBeNull()
    expect(q.open.map((e) => e.entry_id)).toEqual(['h1', 'n1', 't2', 'n5'])
    expect(q.remaining).toBe(4)
    expect(queueOf([], [], true, null).open).toEqual([])
  })

  it('reads a task row off its VTODO: done or cancelled is finished, gone is finished once loaded', () => {
    const s = session({ entry_id: 't2' })
    expect(queueOf(rows, [task({ completed: true })], true, s).current).toBeNull()
    expect(queueOf(rows, [task({ cancelled: true })], true, s).current).toBeNull()
    expect(queueOf(rows, [], true, s).current).toBeNull()
    // Before the tasks have loaded a task row is open — the surface must not
    // decide a row is gone off a blank.
    expect(queueOf(rows, [], false, s).current?.entry_id).toBe('t2')
  })

  it('reports the one fact that may trigger a sync: the named row is finished', () => {
    expect(currentFinished(rows, [task()], true, session({ entry_id: 't2' }))).toBe(false)
    expect(currentFinished(rows, [task({ completed: true })], true, session({ entry_id: 't2' }))).toBe(true)
    expect(currentFinished(rows, [], true, session({ entry_id: 'n3' }))).toBe(true)
    expect(currentFinished(rows, [], true, session({ entry_id: 'n4' }))).toBe(true)
    expect(currentFinished(rows, [], true, session({ entry_id: 'nope' }))).toBe(true)
    expect(currentFinished(rows, [], true, session({ entry_id: null }))).toBe(false)
    expect(currentFinished(rows, [], true, null)).toBe(false)
    // A disagreement about what is NEXT is not a fact: an open named row stays.
    expect(currentFinished(rows, [], true, session({ entry_id: 'n5' }))).toBe(false)
  })
})

describe('the settings', () => {
  it('fill every absent key from the defaults', () => {
    expect(sanitizeFocusSettings(undefined)).toEqual(DEFAULT_FOCUS)
    expect(sanitizeFocusSettings({})).toEqual(DEFAULT_FOCUS)
  })

  it('clamp a hand-edited blob rather than obeying it', () => {
    const got = sanitizeFocusSettings({
      focus_interval_minutes: 0, focus_break_minutes: 999, focus_long_break_every: -3,
      focus_long_break_minutes: 12.6, focus_auto_continue: true, focus_chime: false,
      // junk types
      ...({ focus_cap_default: 'yes', focus_notify: 1 } as object),
    })
    expect(got).toEqual({
      ...DEFAULT_FOCUS, interval: 1, brk: 60, longEvery: 0, longBrk: 13,
      autoContinue: true, chime: false,
    })
  })
})
