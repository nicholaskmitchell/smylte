// Month-grid and event-bucketing math, kept free of React so it can be reasoned
// about and tested on its own — the same split dashboard.ts makes for the Home
// grid. Both the Calendar tab and the Home mini calendar render a six-week
// month, so they share one definition of "which days does this event cover".

import type { CalEvent, Task } from './api'
import { sortTasks } from './order'
import { addDays, dayKey, hasZone, instantFromLocal, pad, parseDate, toLocalInput, ymd } from './util'

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

/** Shift an ISO date or datetime by n days, preserving the wall clock.
 *
 * A value that names an INSTANT comes back as an instant; a floating one comes
 * back floating. That distinction is the whole point. This used to flatten
 * everything to `${ymd}T${HH}:${MM}` in the viewer's own wall clock, with no
 * offset — so dragging an event another CalDAV client had written with
 * `DTSTART;TZID=Europe/Berlin` sent back a naive string, `_set_datelike` wrote
 * it verbatim, and the TZID was gone. For a viewer in a different zone the
 * event also silently moved by the offset difference. That is invariant #2:
 * never lose properties you did not author.
 *
 * The backend re-expresses an incoming instant in the property's own tzinfo, so
 * emitting one here is what keeps the zone. TasksView already does this for DUE
 * through `dateOut`; this is the same rule on the event side. */
export const shiftIso = (v: string, n: number) => {
  if (!v.includes('T')) return shiftYmd(v, n)
  const d = addDays(parseDate(v), n)
  return hasZone(v) ? d.toISOString() : `${ymd(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** Milliseconds in an iCalendar DURATION (RFC 5545 §3.3.6), or null.
 *
 * Weeks are exclusive of the other parts in the grammar, and a leading `-` is
 * legal. Anything that does not parse cleanly returns null rather than a guess:
 * the caller's fallback is to leave the stored span alone, which is always
 * safer than writing a made-up one. */
export function durationMs(d: string | null | undefined): number | null {
  if (!d) return null
  const m = /^([+-])?P(?:(\d+)W|(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?)$/.exec(d.trim())
  if (!m) return null
  const [, sign, w, dd, hh, mm, ss] = m
  if (!w && !dd && !hh && !mm && !ss) return null      // bare "P" / "PT"
  const ms = (Number(w || 0) * 7 + Number(dd || 0)) * 86400000
    + Number(hh || 0) * 3600000 + Number(mm || 0) * 60000 + Number(ss || 0) * 1000
  return sign === '-' ? -ms : ms
}

/** The datetime-local value `start + duration` names, or null if it cannot be
 * derived. Used to seed the edit modal for a VEVENT that carries DURATION
 * instead of DTEND. */
export function endFromDuration(start: string, duration: string | null | undefined): string | null {
  const ms = durationMs(duration)
  if (ms === null) return null
  const d = parseDate(start)
  if (isNaN(d.getTime())) return null
  const out = new Date(d.getTime() + ms)
  return `${ymd(out)}T${pad(out.getHours())}:${pad(out.getMinutes())}`
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
  // Sort on the instant each start NAMES, not on the wire string. Events from
  // another CalDAV client come back with an offset (`2026-08-03T19:00:00+01:00`)
  // while the ones this app wrote are floating (`2026-08-03T16:00:00`), and the
  // lexicographic order of those two has nothing to do with their local order
  // whenever the offset differs from the viewer's. That is not only a reorder
  // of chips: the cell renders `dayEvents.slice(0, 4)` in array order and hides
  // the rest behind "+N more", so a mis-sort can push an earlier event out of
  // the cell while a later one stays, and HomeView's dot colors walk the same
  // array. All-day entries sort first — they are the day, not a time in it.
  for (const evs of m.values()) evs.sort(startOrder)
  return m
}

const startOrder = (a: DayEv, b: DayEv) => {
  const aDay = !!(a.all_day || a.start_is_date)
  const bDay = !!(b.all_day || b.start_is_date)
  if (aDay !== bDay) return aDay ? -1 : 1
  const at = a.start ? parseDate(a.start).getTime() : 0
  const bt = b.start ? parseDate(b.start).getTime() : 0
  if (isNaN(at) || isNaN(bt) || at === bt) {
    return (a.start || '').localeCompare(b.start || '')   // stable, and never NaN
  }
  return at - bt
}

/** The tasks falling on each day of `days`, keyed by `ymd`.
 *
 * Far simpler than `bucketByDay` because a task is a point in time, not a span:
 * a VTODO has a DUE and optionally a DTSTART, but no end and no duration, so
 * there is nothing to walk and no continuation days to mark. A task with no due
 * date has no day to sit on and is left out entirely — the tasks pane is where
 * those live.
 *
 * Within a day they take the app's one task order (see order.ts), so a day cell
 * and the tasks pane agree about which comes first.
 */
export function bucketTasksByDay(tasks: Task[], days: Date[]): Map<string, Task[]> {
  const m = new Map<string, Task[]>()
  if (!days.length) return m
  const first = ymd(days[0])
  const last = ymd(days[days.length - 1])
  for (const t of tasks) {
    if (!t.due) continue
    // An unparseable due would key the map on "NaN-NaN-NaN", which no cell
    // renders — skip it rather than build a bucket nothing reads.
    if (isNaN(parseDate(t.due).getTime())) continue
    const day = dayKey(t.due)
    if (day < first || day > last) continue
    const bucket = m.get(day)
    if (bucket) bucket.push(t)
    else m.set(day, [t])
  }
  for (const [day, ts] of m) m.set(day, sortTasks(ts))
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
  if (ev.all_day) return { start, end }
  // Everything above works in the viewer's wall clock, which is what the
  // no-op guards compare. Convert back out only here, and only for a value
  // that named an instant to begin with: a resize must not turn
  // `DTSTART;TZID=Europe/Berlin` into a floating local time, which is the same
  // loss the move branch had. The start is pinned by definition, so it goes
  // back verbatim rather than being re-derived.
  return {
    start: hasZone(ev.start) ? ev.start : start,
    end: hasZone(ev.end || ev.start)
      ? instantFromLocal(end.slice(0, 10), end.slice(11, 16))
      : end,
  }
}

// ── the grid's shape ────────────────────────────────────────────────────────
// A month cell used to size itself to whatever it held: `.cal-cell` carries a
// min-height and the grid's rows are `auto`, so one day with four chips and a
// "+N more" button made its whole week taller than the quiet weeks around it,
// and the six rows together outgrew the pane. That is `dynamic`, and it stays
// the default. `fixed` splits the pane evenly between the six weeks instead, so
// the month always draws the same shape and a busy day collapses into "+N more"
// rather than stretching its row.

export type CalendarFit = 'dynamic' | 'fixed'

/** The shape the grid has always had, and what an account gets until it says
 *  otherwise. */
export const DEFAULT_CALENDAR_FIT: CalendarFit = 'dynamic'

// Settings are a JSON blob a user can hand-edit, so the stored value is
// re-validated on the way in rather than trusted (same as isTimeFormat).
export function isCalendarFit(v: unknown): v is CalendarFit {
  return v === 'dynamic' || v === 'fixed'
}

/** Two values, so the settings row cycles like the clock rather than offering a
 *  picker. */
export function nextCalendarFit(f: CalendarFit): CalendarFit {
  return f === 'fixed' ? 'dynamic' : 'fixed'
}

export function calendarFitLabel(f: CalendarFit): string {
  return f === 'fixed' ? 'Fixed' : 'Dynamic'
}

/** One day cell's vertical layout, in px, as read off the rendered grid.
 *
 * `inner` is the content box: the cell's height with its own padding taken off.
 * `head` is the date number above the chips, `chip` one chip, `gap` the flex
 * gap that sits between every adjacent pair. */
export interface CellMetrics {
  inner: number
  head: number
  chip: number
  gap: number
}

/**
 * How many chips fit in a cell of these measurements, or null when they say
 * nothing usable.
 *
 * A fixed cell's height comes from the pane, and a chip's from `--fs-scale` and
 * the chosen font — neither is a constant this module could hold, so the cap is
 * measured rather than assumed. That is what keeps "+N more" honest: a guessed
 * cap either hides events a taller cell had room for, or promises chips that
 * get clipped.
 *
 * Null is the "don't know yet" answer, and the caller keeps whatever cap it had:
 * it comes back for an unmeasured layout (jsdom, a display:none pane, the paint
 * before the first chip exists) rather than a zero that would blank every cell.
 */
export function cellCapacity(m: CellMetrics): number | null {
  const { inner, head, chip, gap } = m
  if (![inner, head, chip, gap].every((n) => Number.isFinite(n) && n >= 0)) return null
  if (inner <= 0 || chip <= 0) return null
  // n chips under the date number occupy head + n * (gap + chip): the flex gap
  // falls between the head and the first chip too.
  return Math.max(0, Math.floor((inner - head) / (chip + gap)))
}

/**
 * How many of a day's `total` chips the cell renders. The remainder is what
 * "+N more" counts.
 *
 * `reserveMore` is the only place the two modes actually differ. A fixed cell
 * cannot grow, so the "+N more" button has to come out of the same height and
 * costs a chip slot; a dynamic cell grows to make room for it, which is what
 * the grid has always done.
 */
export function chipsShown(total: number, cap: number, reserveMore: boolean): number {
  if (total <= cap) return Math.max(0, total)
  return Math.max(0, reserveMore ? cap - 1 : cap)
}
