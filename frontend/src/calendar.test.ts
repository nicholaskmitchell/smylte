import { describe, expect, it } from 'vitest'
import { bucketByDay, lastDayOf, monthGrid } from './calendar'
import type { CalEvent } from './api'

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
