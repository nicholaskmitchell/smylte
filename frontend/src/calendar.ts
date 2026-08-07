// Month-grid and event-bucketing math, kept free of React so it can be reasoned
// about and tested on its own — the same split dashboard.ts makes for the Home
// grid. Both the Calendar tab and the Home mini calendar render a six-week
// month, so they share one definition of "which days does this event cover".

import type { CalEvent } from './api'
import { addDays, dayKey, pad, parseDate, toLocalInput, ymd } from './util'

/** A calendar-cell entry: `cont` marks days after the first of a multi-day span. */
export type DayEv = CalEvent & { cont?: boolean }

export const shiftYmd = (day: string, n: number) => ymd(addDays(new Date(`${day}T00:00`), n))

/** Whole calendar days from day `a` to day `b`.
 *
 * The rounding is load-bearing, not defensive: a span containing a DST
 * transition is 23 or 25 hours long, so the raw millisecond quotient comes out
 * at 2.958 or 3.042 days. Anything that wants a day count — not an elapsed
 * duration — has to round, or it loses a day across a spring-forward. */
export const daysBetween = (a: string, b: string) =>
  Math.round((new Date(`${b}T00:00`).getTime() - new Date(`${a}T00:00`).getTime()) / 86400000)

/** Shift an ISO date or datetime by n days. Datetimes come back as floating
 * local wall time — the same form the edit modal writes. */
export const shiftIso = (v: string, n: number) => {
  if (!v.includes('T')) return shiftYmd(v, n)
  const d = addDays(parseDate(v), n)
  return `${ymd(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** Is this event's DTEND exclusive — i.e. does it name an instant the event does
 * not actually cover? True for an all-day end (RFC 5545) and for a timed end
 * sitting exactly on local midnight, which belongs to the previous day.
 * `lastDayOf` backs both off by a day; anything writing a new end has to put it
 * back the same way, or the event lands a day short of where the user put it. */
export function endIsExclusive(e: Pick<CalEvent, 'end' | 'end_is_date'>): boolean {
  if (!e.end) return false
  if (e.end_is_date) return true
  const end = parseDate(e.end)
  return e.end.includes('T') && end.getHours() === 0 && end.getMinutes() === 0
}

// Last visible day of an event. DTEND is exclusive for all-day events, and a
// timed event ending exactly at midnight shouldn't spill into the next day.
// Days come from dayKey/parseDate so events written with a UTC offset (e.g. by
// another CalDAV client) land on the viewer's local day.
export function lastDayOf(e: CalEvent): string {
  const startDay = dayKey(e.start!)
  if (!e.end) return startDay
  const endDay = ymd(parseDate(e.end))
  const last = endIsExclusive(e) ? shiftYmd(endDay, -1) : endDay
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

/** The PATCH body for a desktop drag, or null when the drag is a no-op.
 *
 * Split out of CalendarView's `dropOnDay` so the date arithmetic — which is
 * where every drag bug in this view has lived — can be exercised directly
 * rather than through a synthetic drag event. The component keeps the parts
 * that are genuinely about the component: reading drag state, and routing a
 * recurring event to the scope prompt.
 *
 * `mode: 'move'` shifts start and end together by the whole-day delta from the
 * dragged segment's own cell (so a continuation segment of a multi-day span, or
 * one clipped by the grid window, still moves by what the user sees).
 * `mode: 'resize'` pins the start and puts the last day on `toDay`.
 */
export function dragBody(
  ev: CalEvent, fromDay: string, toDay: string, mode: 'move' | 'resize',
): Record<string, unknown> | null {
  if (!ev.start) return null

  if (mode === 'move') {
    const delta = daysBetween(fromDay, toDay)
    if (!delta) return null
    const body: Record<string, unknown> = { start: shiftIso(ev.start, delta) }
    if (ev.end) body.end = shiftIso(ev.end, delta)
    return body
  }

  const startDay = dayKey(ev.start)
  const day = toDay < startDay ? startDay : toDay      // never drag the end past the start
  const start = ev.all_day ? ev.start.slice(0, 10) : toLocalInput(ev.start)
  let end: string
  if (ev.all_day) {
    end = shiftYmd(day, 1)                             // DTEND stays exclusive
  } else if (endIsExclusive(ev)) {
    // A timed event ending exactly at midnight ends *at the start of* that day,
    // so the day the user dropped on is only covered if the end moves past it.
    // Writing `${day}T00:00` instead named the day before: dragging the grip one
    // day out compared equal to the old end and was silently discarded, and
    // dragging it further landed the event a day short of the drop.
    end = `${shiftYmd(day, 1)}T00:00`
  } else {
    end = `${day}T${toLocalInput(ev.end || ev.start).slice(11, 16)}`
    if (end <= start) return null                      // the end must stay after the start
  }
  const oldEnd = ev.end && (ev.all_day ? ev.end.slice(0, 10) : toLocalInput(ev.end))
  if (end === oldEnd) return null
  return { start, end }
}
