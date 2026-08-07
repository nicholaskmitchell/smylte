// Month-grid and event-bucketing math, kept free of React so it can be reasoned
// about and tested on its own — the same split dashboard.ts makes for the Home
// grid. Both the Calendar tab and the Home mini calendar render a six-week
// month, so they share one definition of "which days does this event cover".

import type { CalEvent } from './api'
import { addDays, dayKey, parseDate, ymd } from './util'

/** A calendar-cell entry: `cont` marks days after the first of a multi-day span. */
export type DayEv = CalEvent & { cont?: boolean }

export const shiftYmd = (day: string, n: number) => ymd(addDays(new Date(`${day}T00:00`), n))

// Last visible day of an event. DTEND is exclusive for all-day events, and a
// timed event ending exactly at midnight shouldn't spill into the next day.
// Days come from dayKey/parseDate so events written with a UTC offset (e.g. by
// another CalDAV client) land on the viewer's local day.
export function lastDayOf(e: CalEvent): string {
  const startDay = dayKey(e.start!)
  if (!e.end) return startDay
  const end = parseDate(e.end)
  const endDay = ymd(end)
  const exclusive = e.end_is_date ||
    (e.end.includes('T') && end.getHours() === 0 && end.getMinutes() === 0)
  const last = exclusive ? shiftYmd(endDay, -1) : endDay
  return last < startDay ? startDay : last
}

/** The six-week grid for `cursor`'s month: 42 days, Sunday-first. */
export function monthGrid(cursor: Date): Date[] {
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
  const start = addDays(first, -first.getDay())
  return Array.from({ length: 42 }, (_, i) => addDays(start, i))
}

/** The events falling on each day of `days`, keyed by `ymd`.
 *
 * A span is listed on every day it covers, so a week-long event is not invisible
 * on the six days after the one it starts; days after the first carry `cont`.
 * The walk is clipped to the grid at both ends — an event may legitimately run
 * from years ago to years ahead, and stepping a day at a time to reach a far
 * DTEND (trivially written by another CalDAV client) would freeze the tab
 * building entries nothing renders. */
export function bucketByDay(events: CalEvent[], days: Date[]): Map<string, DayEv[]> {
  const m = new Map<string, DayEv[]>()
  if (!days.length) return m
  const first = ymd(days[0])
  const last = ymd(days[days.length - 1])
  for (const e of events) {
    if (!e.start) continue
    // Unparseable dates are skipped rather than bucketed: `lastDayOf` would
    // return "NaN-NaN-NaN", which string-compares above every real day and so
    // would spread the event across the whole remaining grid.
    const from = parseDate(e.start)
    const to = e.end ? parseDate(e.end) : from
    if (isNaN(from.getTime()) || isNaN(to.getTime())) continue
    const startDay = dayKey(e.start)
    const endDay = lastDayOf(e)
    let day = startDay < first ? first : startDay
    const stop = endDay > last ? last : endDay
    for (let i = 0; day <= stop && i < days.length; i++, day = shiftYmd(day, 1)) {
      const bucket = m.get(day)
      const entry = day === startDay ? e : { ...e, cont: true }
      if (bucket) bucket.push(entry)
      else m.set(day, [entry])
    }
  }
  for (const evs of m.values()) evs.sort((a, b) => (a.start || '').localeCompare(b.start || ''))
  return m
}
