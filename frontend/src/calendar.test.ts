import { describe, expect, it } from 'vitest'
import {
  bucketByDay, bucketTasksByDay, dragBody, daysBetween, endIsExclusive, lastDayOf,
  monthGrid, shiftIso,
} from './calendar'
import type { CalEvent, Task } from './api'

const ev = (start: string | null, end: string | null,
  o: Partial<CalEvent> = {}): CalEvent => ({
  uid: 'e', id: 'e', recurrence_id: null, is_recurring: false, calendar: 'c',
  summary: 'E', description: null, location: null,
  start, start_is_date: false, end, end_is_date: false,
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
