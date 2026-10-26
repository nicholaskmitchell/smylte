// The pure half of the share page: clock math, poll timing and agenda shaping,
// kept free of React so each can be reasoned about and tested on its own — the
// same split focus.ts and calendar.ts make for their screens.
//
// The viewer's device clock is not trusted. A tablet on a kitchen wall can be
// minutes or hours off, and a countdown computed from `ends_at` against that
// clock would be wrong by the same amount. `skewOf` measures the difference
// between the server's `generated_at` and the moment the response arrived, and
// every comparison against a server timestamp below adds it back.

import type { BucketEvent } from './calendar'
import { shiftYmd } from './calendar'
import type { ShareEvent, ShareFocus, ShareFocusState, ShareView } from './api'
import { parseDate } from './util'

/** How long one fetch may take before the page gives up and backs off. A
 *  half-open socket never rejects, and a page nobody is looking at cannot tell
 *  the owner anything is wrong. */
export const FETCH_TIMEOUT_MS = 20_000

/** The grace after a phase ends before the page asks again, so the owner's side
 *  has had time to move on to the next state. */
const AFTER_END_MS = 2_000
const MIN_POLL_MS = 2_000
const BACKOFF_FIRST_MS = 5_000
const BACKOFF_MAX_MS = 60_000

/** Server time minus device time, in ms: add it to `Date.now()` to read the
 *  server's clock. Measured when the response ARRIVES, so it includes the
 *  network delay — a second or so, which a minute-resolution page can ignore
 *  and an hours-off device clock cannot. */
export function skewOf(generatedAt: string, receivedAtMs: number): number {
  return Date.parse(generatedAt) - receivedAtMs
}

const running = (f: ShareFocus) =>
  (f.state === 'focusing' || f.state === 'break') && f.ends_at !== null

/** Seconds left in the current phase, or null when there is no clock to show.
 *  Running phases count down to the fixed `ends_at`, so the answer does not
 *  depend on how long ago the last poll was; a paused one is frozen. */
export function remainingS(f: ShareFocus, nowMs: number, skewMs: number): number | null {
  if (running(f)) {
    return Math.max(0, Math.floor((Date.parse(f.ends_at!) - (nowMs + skewMs)) / 1000))
  }
  if (f.state === 'paused') return f.remaining_s
  return null
}

/** The state to draw NOW. A phase whose end has passed reads as `between`
 *  without waiting for a poll, so the clock never sits at 0:00 saying
 *  "Focusing" until the next fetch lands. */
export function localState(f: ShareFocus, nowMs: number, skewMs: number): ShareFocusState {
  if (running(f) && Date.parse(f.ends_at!) <= nowMs + skewMs) return 'between'
  return f.state
}

/** How far through the phase, 0..1, for the bar. */
export function progress(f: ShareFocus, nowMs: number, skewMs: number): number {
  const state = localState(f, nowMs, skewMs)
  if (state === 'between') return 1
  const length = f.phase_length_s
  if (!length || length <= 0) return 0
  const left = remainingS(f, nowMs, skewMs)
  if (left === null) return 0
  return Math.min(1, Math.max(0, 1 - left / length))
}

/** Milliseconds until the next fetch, or null for "do not schedule one".
 *
 *  A hidden tab does not poll at all: the owner's data is not worth a request
 *  nobody can see, and it refetches at once on becoming visible. Failures back
 *  off from 5 s to a minute. Otherwise the server's own `poll_seconds`, pulled
 *  forward to just after a running phase ends so the next state shows up
 *  promptly rather than up to 30 s late. */
export function nextPollDelay(o: {
  view: ShareView | null; failures: number; hidden: boolean; nowMs: number; skewMs: number
}): number | null {
  if (o.hidden) return null
  if (o.failures > 0) {
    return Math.min(BACKOFF_MAX_MS, BACKOFF_FIRST_MS * 2 ** (o.failures - 1))
  }
  if (!o.view) return BACKOFF_FIRST_MS
  let delay = o.view.poll_seconds * 1000
  const f = o.view.focus
  if (f && running(f)) {
    const untilEnd = Date.parse(f.ends_at!) - (o.nowMs + o.skewMs) + AFTER_END_MS
    if (untilEnd > 0 && untilEnd < delay) delay = untilEnd
  }
  return Math.max(MIN_POLL_MS, delay)
}

/** Whether the page has gone long enough without a good answer that what it
 *  shows may be out of date. Scaled to the poll interval, with a floor, so a
 *  slow-polling share is not flagged for one missed beat. */
export function isStale(fetchedAtMs: number | null, view: ShareView | null, nowMs: number): boolean {
  if (fetchedAtMs === null || !view) return false
  return nowMs - fetchedAtMs > Math.max(120_000, view.poll_seconds * 2_500)
}

/** The agenda's days: `days` consecutive dates starting at the VIEWER's own
 *  today, not the owner's. The server sends a window one day wider on each side
 *  precisely so that, whichever side of the date line the viewer is on, every
 *  one of these days has its events; starting from the owner's `day` would show
 *  a viewer in Auckland yesterday's events as today's. */
export function agendaDays(viewerTodayYmd: string, days: number): string[] {
  return Array.from({ length: days }, (_, i) => shiftYmd(viewerTodayYmd, i))
}

/** A share event in the shape `bucketByDay` reads. The wire has no separate
 *  "start is a date" flags: an all-day event's start and end are both dates. */
export function toBucket(e: ShareEvent): ShareEvent & BucketEvent {
  return { ...e, start_is_date: e.all_day, end_is_date: e.all_day }
}

/** The timed event happening at `nowMs`, for "In 'Standup' until 10:30". All-day
 *  events are left out: being "in" a conference that spans the week says nothing
 *  about the next hour. The earliest start wins when several overlap. */
export function ongoingEvent(events: ShareEvent[], nowMs: number): ShareEvent | null {
  let best: ShareEvent | null = null
  let bestStart = Infinity
  for (const e of events) {
    if (e.all_day || !e.end) continue
    const start = parseDate(e.start).getTime()
    const end = parseDate(e.end).getTime()
    if (isNaN(start) || isNaN(end)) continue
    if (start <= nowMs && nowMs < end && start < bestStart) {
      best = e
      bestStart = start
    }
  }
  return best
}

/** A time of day in the VIEWER's own zone and 12/24-hour convention, which the
 *  locale carries. The owner's setting is deliberately not sent. */
export function fmtTime(iso: string, locale: string): string {
  return parseDate(iso).toLocaleTimeString(locale, { hour: 'numeric', minute: '2-digit' })
}

/** An agenda heading: the words for today and tomorrow are the caller's to
 *  translate, so those come back as markers rather than English. */
export function fmtDayLabel(ymdStr: string, todayYmd: string, locale: string): 'today' | 'tomorrow' | string {
  if (ymdStr === todayYmd) return 'today'
  if (ymdStr === shiftYmd(todayYmd, 1)) return 'tomorrow'
  return parseDate(ymdStr).toLocaleDateString(locale,
    { weekday: 'long', month: 'long', day: 'numeric' })
}
