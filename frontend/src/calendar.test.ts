import { describe, expect, it } from 'vitest'
import {
  DEFAULT_CALENDAR_FIT, bucketByDay, bucketTasksByDay, calendarFitLabel, cellCapacity,
  chipsShown, dragBody, daysBetween, endIsExclusive, isCalendarFit, lastDayOf, monthGrid,
  nextCalendarFit, shiftIso,
} from './calendar'
import type { CalEvent, Task } from './api'

const ev = (start: string | null, end: string | null,
  o: Partial<CalEvent> = {}): CalEvent => ({
  uid: 'e', id: 'e', recurrence_id: null, is_recurring: false, calendar: 'c',
  summary: 'E', description: null, location: null,
  start, start_is_date: false, end, end_is_date: false, duration: null,
  all_day: false, status: null, tags: [], has_rrule: false, href: '/c/e.ics', etag: '"1"',
  ...o,
})

const grid = Array.from({ length: 42 }, (_, i) => {
  const d = new Date(2026, 6, 28)          // 2026-07-28 .. 2026-09-07
  d.setDate(d.getDate() + i)
  return d
})

const keys = (m: Map<string, unknown>) => [...m.keys()].sort()

describe('bucketByDay', () => {
  // Ordering within a cell was a string compare on the wire value. Events
  // another CalDAV client wrote carry an offset; the ones this app wrote are
  // floating. Under TZ=America/New_York, `2026-08-03T19:00:00+01:00` is 14:00
  // local — earlier than a floating `2026-08-03T16:00:00` — but sorts after it
  // as a string. The cell renders only the first four and hides the rest behind
  // "+N more", so this could push an earlier event out of view entirely.
  it('orders a day by the instant each start names, not the wire string', () => {
    const zoned = ev('2026-08-03T19:00:00+01:00', '2026-08-03T20:00:00+01:00', { uid: 'zoned' })
    const floating = ev('2026-08-03T16:00:00', '2026-08-03T17:00:00', { uid: 'floating' })
    const day = bucketByDay([floating, zoned], grid).get('2026-08-03')!
    expect(day.map((e) => e.uid)).toEqual(['zoned', 'floating'])
  })

  it('keeps all-day entries at the top of the cell', () => {
    const allDay = ev('2026-08-03', '2026-08-04',
      { uid: 'allday', all_day: true, start_is_date: true, end_is_date: true })
    const early = ev('2026-08-03T01:00:00', '2026-08-03T02:00:00', { uid: 'early' })
    const day = bucketByDay([early, allDay], grid).get('2026-08-03')!
    expect(day.map((e) => e.uid)).toEqual(['allday', 'early'])
  })

  it('lists an event on every day its span covers', () => {
    const m = bucketByDay([ev('2026-08-03T09:00:00', '2026-08-05T10:00:00')], grid)
    expect(keys(m)).toEqual(['2026-08-03', '2026-08-04', '2026-08-05'])
  })

  it('lists a single day for an event with no end', () => {
    expect(keys(bucketByDay([ev('2026-08-03T09:00:00', null)], grid))).toEqual(['2026-08-03'])
  })

  it('keeps the final day even when the end is earlier in the day than the start', () => {
    // Whole-day comparison: carrying the 09:00 start into the bound check used
    // to drop 08-05 here, because 08-05T09:00 sorts after the 08:00 end.
    expect(keys(bucketByDay([ev('2026-08-03T09:00:00', '2026-08-05T08:00:00')], grid)))
      .toEqual(['2026-08-03', '2026-08-04', '2026-08-05'])
  })

  it('clamps a span that runs far past the grid instead of walking to its end', () => {
    // A DTEND millennia out is trivially written by another CalDAV client.
    // Unclamped this stepped a day at a time to reach it and froze the tab.
    const t = performance.now()
    const m = bucketByDay([ev('2026-08-03T09:00:00', '9999-12-31T10:00:00')], grid)
    expect(performance.now() - t).toBeLessThan(500)
    expect(m.size).toBe(36)                  // 2026-08-03 .. 2026-09-07, no further
    expect(m.has('2026-09-07')).toBe(true)
    expect(m.has('2026-09-08')).toBe(false)
  })

  it('clamps a span that started long before the grid', () => {
    const t = performance.now()
    const m = bucketByDay([ev('1900-01-01T09:00:00', '2026-08-01T10:00:00')], grid)
    expect(performance.now() - t).toBeLessThan(500)
    expect(keys(m)).toEqual(['2026-07-28', '2026-07-29', '2026-07-30',
      '2026-07-31', '2026-08-01'])
  })

  it('skips events whose dates do not parse', () => {
    // Without the guard lastDayOf returns "NaN-NaN-NaN", which string-compares
    // above every real day — the event would land on the whole rest of the grid.
    expect(bucketByDay([ev('nonsense', 'also-nonsense')], grid).size).toBe(0)
    expect(bucketByDay([ev('2026-08-03T09:00:00', 'nonsense')], grid).size).toBe(0)
  })

  it('treats an all-day DTEND as exclusive', () => {
    const m = bucketByDay(
      [ev('2026-08-03', '2026-08-06', { start_is_date: true, end_is_date: true, all_day: true })],
      grid)
    expect(keys(m)).toEqual(['2026-08-03', '2026-08-04', '2026-08-05'])
  })

  it('does not spill an event that ends exactly at midnight into the next day', () => {
    const m = bucketByDay([ev('2026-08-03T09:00:00', '2026-08-04T00:00:00')], grid)
    expect(keys(m)).toEqual(['2026-08-03'])
  })

  it('marks every day after the first as a continuation', () => {
    const m = bucketByDay([ev('2026-08-03T09:00:00', '2026-08-05T10:00:00')], grid)
    expect(m.get('2026-08-03')![0].cont).toBeUndefined()
    expect(m.get('2026-08-04')![0].cont).toBe(true)
    expect(m.get('2026-08-05')![0].cont).toBe(true)
  })

  it('sorts each day by start time', () => {
    const m = bucketByDay([
      ev('2026-08-03T15:00:00', null, { id: 'late', summary: 'Late' }),
      ev('2026-08-03T09:00:00', null, { id: 'early', summary: 'Early' }),
    ], grid)
    expect(m.get('2026-08-03')!.map((e) => e.id)).toEqual(['early', 'late'])
  })

  it('returns an empty map for an empty grid', () => {
    expect(bucketByDay([ev('2026-08-03T09:00:00', null)], []).size).toBe(0)
  })
})

describe('lastDayOf', () => {
  it('is the start day when there is no end', () => {
    expect(lastDayOf(ev('2026-08-03T09:00:00', null))).toBe('2026-08-03')
  })

  it('backs off an exclusive all-day end', () => {
    expect(lastDayOf(ev('2026-08-03', '2026-08-06', { end_is_date: true }))).toBe('2026-08-05')
  })

  it('never falls before the start day', () => {
    expect(lastDayOf(ev('2026-08-03T09:00:00', '2026-08-01T10:00:00'))).toBe('2026-08-03')
  })
})

describe('monthGrid', () => {
  it('is six Sunday-first weeks containing the cursor month', () => {
    const days = monthGrid(new Date(2026, 7, 15))     // August 2026
    expect(days).toHaveLength(42)
    expect(days[0].getDay()).toBe(0)
    expect(days.some((d) => d.getMonth() === 7 && d.getDate() === 1)).toBe(true)
    expect(days.some((d) => d.getMonth() === 7 && d.getDate() === 31)).toBe(true)
  })

  it('starts on the 1st when the month already begins on a Sunday', () => {
    const days = monthGrid(new Date(2026, 10, 20))    // November 2026 starts Sunday
    expect(days[0].getMonth()).toBe(10)
    expect(days[0].getDate()).toBe(1)
  })
})

// The suite is pinned to America/New_York (vite.config.ts) so these are real
// transitions: 2026-03-08 springs forward, 2026-11-01 falls back.
describe('daysBetween', () => {
  it('counts plain days', () => {
    expect(daysBetween('2026-08-03', '2026-08-06')).toBe(3)
    expect(daysBetween('2026-08-06', '2026-08-03')).toBe(-3)
    expect(daysBetween('2026-08-03', '2026-08-03')).toBe(0)
  })

  it('counts whole days across a spring-forward, not 23-hour days', () => {
    // The raw quotient here is 2.958 — truncating loses the day.
    expect((new Date('2026-03-10T00:00').getTime()
      - new Date('2026-03-07T00:00').getTime()) / 86400000).toBeCloseTo(2.958, 2)
    expect(daysBetween('2026-03-07', '2026-03-10')).toBe(3)
  })

  it('counts whole days across a fall-back', () => {
    expect(daysBetween('2026-10-31', '2026-11-03')).toBe(3)
  })
})

describe('shiftIso', () => {
  it('shifts a date-only value', () => {
    expect(shiftIso('2026-08-03', 2)).toBe('2026-08-05')
    expect(shiftIso('2026-08-03', -2)).toBe('2026-08-01')
  })

  it('shifts a datetime and returns floating local wall time', () => {
    expect(shiftIso('2026-08-03T09:30:00', 2)).toBe('2026-08-05T09:30')
  })

  it('keeps the wall-clock time across a spring-forward', () => {
    // 09:00 stays 09:00 — a meeting does not move to 10:00 because the clocks did.
    expect(shiftIso('2026-03-07T09:00:00', 2)).toBe('2026-03-09T09:00')
  })

  it('keeps the wall-clock time across a fall-back', () => {
    expect(shiftIso('2026-10-31T09:00:00', 2)).toBe('2026-11-02T09:00')
  })

  // The whole point of the distinction: a value that names an INSTANT has to
  // come back as one. Flattening it to the viewer's wall clock threw away the
  // TZID another CalDAV client wrote (the backend only re-expresses a value
  // into the property's own zone when the incoming one is zone-aware; a naive
  // string is written verbatim) and, for a viewer in a different zone, moved
  // the event by the offset difference. Tests run under TZ=America/New_York.
  it.each([
    ['a +02:00 start', '2026-08-03T09:30:00+02:00', 2, '2026-08-05T07:30:00.000Z'],
    ['a UTC start', '2026-08-03T09:30:00Z', 2, '2026-08-05T09:30:00.000Z'],
    ['a backwards shift', '2026-08-03T09:30:00+02:00', -2, '2026-08-01T07:30:00.000Z'],
  ])('preserves the instant for %s', (_label, input, n, expected) => {
    expect(shiftIso(input, n)).toBe(expected)
  })

  it('holds a zoned event at the hour the viewer sees, across a fall-back', () => {
    // A drag moves the chip the user is looking at, so the clock preserved is
    // theirs: 09:00+01:00 renders as 04:00 in New York, and two cells later it
    // is still 04:00 there. Crossing the US transition (and not Berlin's) that
    // means the event's own local time shifts by the hour the viewer's zone
    // moved — unavoidable without knowing the event's zone rather than just its
    // offset at one instant, and the same rule already applied to floating
    // values. What must NOT happen is the value ceasing to name an instant.
    const out = shiftIso('2026-10-31T09:00:00+01:00', 2)
    expect(new Date(out).getHours()).toBe(4)        // viewer-local 04:00, preserved
    expect(out).toMatch(/Z$/)                       // still an instant, not floating
  })
})

describe('endIsExclusive', () => {
  it.each([
    ['no end', { end: null, end_is_date: false }, false],
    ['all-day end', { end: '2026-08-06', end_is_date: true }, true],
    ['timed end at midnight', { end: '2026-08-06T00:00:00', end_is_date: false }, true],
    ['timed end mid-day', { end: '2026-08-06T17:00:00', end_is_date: false }, false],
    ['timed end at 00:30', { end: '2026-08-06T00:30:00', end_is_date: false }, false],
  ])('%s', (_label, e, expected) => {
    expect(endIsExclusive(e as Parameters<typeof endIsExclusive>[0])).toBe(expected)
  })
})

describe('dragBody: move', () => {
  const timed = ev('2026-08-03T09:00:00', '2026-08-03T10:00:00')

  it('keeps a zone-anchored event anchored', () => {
    // Before the fix this sent `2026-08-06T03:00` — naive, so the backend wrote
    // it verbatim and `DTSTART;TZID=Europe/Berlin` became a floating value.
    const zoned = ev('2026-08-03T09:00:00+02:00', '2026-08-03T10:00:00+02:00')
    const body = dragBody(zoned, '2026-08-03', '2026-08-06', 'move')
    expect(body).toEqual({
      start: '2026-08-06T07:00:00.000Z',
      end: '2026-08-06T08:00:00.000Z',
    })
  })

  it('shifts start and end by the whole-day delta', () => {
    expect(dragBody(timed, '2026-08-03', '2026-08-06', 'move'))
      .toEqual({ start: '2026-08-06T09:00', end: '2026-08-06T10:00' })
  })

  it('is a no-op when the event is dropped on its own day', () => {
    expect(dragBody(timed, '2026-08-03', '2026-08-03', 'move')).toBeNull()
  })

  it('omits the end for an event that has none', () => {
    expect(dragBody(ev('2026-08-03T09:00:00', null), '2026-08-03', '2026-08-04', 'move'))
      .toEqual({ start: '2026-08-04T09:00' })
  })

  it('anchors the delta to the dragged segment, not the event start', () => {
    // Dragging the 08-05 continuation segment of an 08-03..08-05 span onto 08-06
    // moves the whole event by one day, not by three.
    const span = ev('2026-08-03T09:00:00', '2026-08-05T10:00:00')
    expect(dragBody(span, '2026-08-05', '2026-08-06', 'move'))
      .toEqual({ start: '2026-08-04T09:00', end: '2026-08-06T10:00' })
  })

  it('keeps the wall-clock time when the move crosses a spring-forward', () => {
    expect(dragBody(ev('2026-03-07T09:00:00', '2026-03-07T10:00:00'),
      '2026-03-07', '2026-03-09', 'move'))
      .toEqual({ start: '2026-03-09T09:00', end: '2026-03-09T10:00' })
  })

  it('moves an all-day event by whole days', () => {
    const allDay = ev('2026-08-03', '2026-08-04',
      { all_day: true, start_is_date: true, end_is_date: true })
    expect(dragBody(allDay, '2026-08-03', '2026-08-06', 'move'))
      .toEqual({ start: '2026-08-06', end: '2026-08-07' })
  })

  it('returns null for an event with no start', () => {
    expect(dragBody(ev(null, null), '2026-08-03', '2026-08-06', 'move')).toBeNull()
  })
})

describe('dragBody: resize', () => {
  it('keeps an all-day DTEND exclusive', () => {
    const allDay = ev('2026-08-03', '2026-08-04',
      { all_day: true, start_is_date: true, end_is_date: true })
    expect(dragBody(allDay, '2026-08-03', '2026-08-06', 'resize'))
      .toEqual({ start: '2026-08-03', end: '2026-08-07' })
  })

  it('resizes a plain timed event to the drop day', () => {
    expect(dragBody(ev('2026-08-03T09:00:00', '2026-08-03T17:00:00'),
      '2026-08-03', '2026-08-05', 'resize'))
      .toEqual({ start: '2026-08-03T09:00', end: '2026-08-05T17:00' })
  })

  it('clamps a drop before the start day back to the start day', () => {
    expect(dragBody(ev('2026-08-03T09:00:00', '2026-08-05T17:00:00'),
      '2026-08-05', '2026-08-01', 'resize'))
      .toEqual({ start: '2026-08-03T09:00', end: '2026-08-03T17:00' })
  })

  it('is a no-op when the end would not move', () => {
    expect(dragBody(ev('2026-08-03T09:00:00', '2026-08-05T17:00:00'),
      '2026-08-05', '2026-08-05', 'resize')).toBeNull()
  })

  it('is a no-op when the new end would not clear the start', () => {
    expect(dragBody(ev('2026-08-03T09:00:00', '2026-08-03T08:00:00'),
      '2026-08-03', '2026-08-03', 'resize')).toBeNull()
  })

  // A 20:00-24:00 block — trivially authored in Thunderbird or Apple Calendar.
  // Its DTEND is exclusive, so it renders (correctly) only on 03-02, and the
  // resize grip sits there. Building the new end as `${day}T00:00` named the day
  // *before* the drop: one day out compared equal to the old end and vanished,
  // and further out landed a day short.
  const midnight = ev('2026-03-02T20:00:00', '2026-03-03T00:00:00')

  it('renders a midnight-ending event on its start day only', () => {
    expect(lastDayOf(midnight)).toBe('2026-03-02')
  })

  it('extends a midnight-ending event by one day instead of discarding the drag', () => {
    const body = dragBody(midnight, '2026-03-02', '2026-03-03', 'resize')
    expect(body).toEqual({ start: '2026-03-02T20:00', end: '2026-03-04T00:00' })
    expect(lastDayOf({ ...midnight, end: body!.end as string })).toBe('2026-03-03')
  })

  it('ends a midnight-ending event on the day it was dropped on', () => {
    const body = dragBody(midnight, '2026-03-02', '2026-03-05', 'resize')
    expect(lastDayOf({ ...midnight, end: body!.end as string })).toBe('2026-03-05')
  })

  it('is still a no-op when a midnight-ending event is dropped on its own last day', () => {
    expect(dragBody(midnight, '2026-03-02', '2026-03-02', 'resize')).toBeNull()
  })

  // The resize branch had the same defect as the move branch, on a path that
  // does not even intend to touch the start: `toLocalInput(ev.start)` rewrote a
  // zone-anchored DTSTART as floating local wall time, so a pure resize
  // destroyed the TZID another client wrote.
  it('leaves a zone-anchored start exactly as it was', () => {
    const zoned = ev('2026-08-03T09:00:00+02:00', '2026-08-03T17:00:00+02:00')
    const body = dragBody(zoned, '2026-08-03', '2026-08-05', 'resize')
    expect(body!.start).toBe('2026-08-03T09:00:00+02:00')
  })

  it('sends the new end as an instant when the old one named one', () => {
    const zoned = ev('2026-08-03T09:00:00+02:00', '2026-08-03T17:00:00+02:00')
    const body = dragBody(zoned, '2026-08-03', '2026-08-05', 'resize')
    // 17:00+02:00 is 11:00 in New York; two days on, still 11:00 there.
    expect(new Date(body!.end as string).getHours()).toBe(11)
    expect(body!.end).toMatch(/Z$/)
  })
})

describe('bucketTasksByDay', () => {
  const t = (o: Partial<Task> = {}): Task => ({
    uid: 't1', list: 'l1', summary: 'Task', notes: null, status: 'NEEDS-ACTION',
    completed: false, cancelled: false, priority: null, priority_label: 'none',
    percent_complete: null, due: '2026-03-04', due_is_date: true,
    start: null, start_is_date: true, tags: [], parent: null, children: [],
    child_count: 0, completed_child_count: 0, derived_percent: null,
    pinned: false, sort_order: null, href: '/l1/t1.ics', etag: '"1"', ...o,
  })
  const days = Array.from({ length: 7 }, (_, i) => new Date(2026, 2, 1 + i))

  it('keys a task on its due day', () => {
    const m = bucketTasksByDay([t()], days)
    expect(m.get('2026-03-04')!.map((x) => x.uid)).toEqual(['t1'])
  })

  it('leaves out a task with no due date', () => {
    // It has no day to sit on; the tasks pane is where those live.
    expect(bucketTasksByDay([t({ due: null })], days).size).toBe(0)
  })

  it('leaves out a task outside the window', () => {
    expect(bucketTasksByDay([t({ due: '2026-05-01' })], days).size).toBe(0)
    expect(bucketTasksByDay([t({ due: '2026-01-01' })], days).size).toBe(0)
  })

  it('lands a zone-anchored due on the viewer\'s local day', () => {
    // 2026-03-05T02:00Z is still the 4th at 21:00 in the suite's New York zone.
    const m = bucketTasksByDay([t({ due: '2026-03-05T02:00:00Z', due_is_date: false })], days)
    expect(m.get('2026-03-04')).toHaveLength(1)
  })

  it('skips an unparseable due rather than keying on NaN', () => {
    expect(bucketTasksByDay([t({ due: 'whenever' })], days).size).toBe(0)
  })

  it('orders a day\'s tasks the way the tasks pane does', () => {
    const m = bucketTasksByDay([
      t({ uid: 'late', due: '2026-03-04T16:00', due_is_date: false }),
      t({ uid: 'allday', due: '2026-03-04', due_is_date: true }),
      t({ uid: 'early', due: '2026-03-04T09:00', due_is_date: false }),
    ], days)
    expect(m.get('2026-03-04')!.map((x) => x.uid)).toEqual(['allday', 'early', 'late'])
  })

  it('returns nothing for an empty grid', () => {
    expect(bucketTasksByDay([t()], []).size).toBe(0)
  })
})

// ── the grid's shape ────────────────────────────────────────────────────────
// A fixed cell's height comes from the pane and a chip's from the account's
// text scale, so the cap has to be measured. These are that arithmetic, given
// the measurements the view reads off the DOM.

describe('calendar fit', () => {
  it('round-trips between the two shapes', () => {
    expect(DEFAULT_CALENDAR_FIT).toBe('dynamic')
    expect(nextCalendarFit('dynamic')).toBe('fixed')
    expect(nextCalendarFit(nextCalendarFit('dynamic'))).toBe('dynamic')
    expect(calendarFitLabel('fixed')).toBe('Fixed')
    expect(calendarFitLabel('dynamic')).toBe('Dynamic')
  })

  it('refuses a stored value it did not write', () => {
    // Settings are a JSON blob a user can hand-edit; anything else falls back
    // to the shipped shape rather than reaching the grid.
    for (const v of ['Fixed', '', 'auto', 0, null, undefined, {}]) {
      expect(isCalendarFit(v)).toBe(false)
    }
    expect(isCalendarFit('fixed')).toBe(true)
    expect(isCalendarFit('dynamic')).toBe(true)
  })
})

describe('cellCapacity', () => {
  // A cell is a flex column: the date number, then a gap before every chip.
  it.each([
    // [inner, head, chip, gap, fits]
    [96, 15, 15, 3, 4],     // the shipped 104px cell, near enough
    [55, 15, 15, 3, 2],     // squeezed to the 64px row floor
    [200, 15, 15, 3, 10],   // a tall pane in a five-week month
    [96, 15, 21, 3, 3],     // the same cell at a larger text scale
    [17, 15, 15, 3, 0],     // no room for even one — "+N more" alone
  ])('fits %i/%i/%i/%i into %i chips', (inner, head, chip, gap, fits) => {
    expect(cellCapacity({ inner, head, chip, gap })).toBe(fits)
  })

  it.each([
    ['an unlaid-out pane', { inner: 0, head: 0, chip: 0, gap: 0 }],
    ['a cell with no chip to measure', { inner: 96, head: 15, chip: 0, gap: 3 }],
    ['a NaN reading', { inner: NaN, head: 15, chip: 15, gap: 3 }],
    ['a negative reading', { inner: -8, head: 15, chip: 15, gap: 3 }],
  ])('answers null for %s', (_what, m) => {
    // Null is "don't know yet", and the view keeps its last usable cap: a zero
    // here would blank every cell behind "+N more" on the first paint.
    expect(cellCapacity(m)).toBeNull()
  })
})

describe('chipsShown', () => {
  it('shows everything that fits, whichever shape the grid has', () => {
    expect(chipsShown(3, 4, false)).toBe(3)
    expect(chipsShown(3, 4, true)).toBe(3)
    expect(chipsShown(4, 4, true)).toBe(4)
  })

  it('spends a slot on "+N more" only where the cell cannot grow', () => {
    // A dynamic cell grows to make room for the button, which is what the grid
    // has always done; a fixed one has to take the room out of its own height.
    expect(chipsShown(9, 4, false)).toBe(4)
    expect(chipsShown(9, 4, true)).toBe(3)
  })

  it('never slices backwards', () => {
    expect(chipsShown(9, 0, true)).toBe(0)
    expect(chipsShown(9, 1, true)).toBe(0)
    expect(chipsShown(0, 4, true)).toBe(0)
  })
})
