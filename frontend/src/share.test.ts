import { afterEach, describe, expect, it } from 'vitest'
import type { ShareEvent, ShareFocus, ShareView } from './api'
import { bucketByDay } from './calendar'
import {
  agendaDays, fmtDayLabel, fmtTime, isStale, localState, nextPollDelay, ongoingEvent,
  progress, remainingS, skewOf, toBucket,
} from './share'
import { ymd } from './util'

const T0 = Date.parse('2026-10-26T10:00:00.000Z')
const HOUR = 3_600_000

const focus = (o: Partial<ShareFocus> = {}): ShareFocus => ({
  state: 'focusing', phase: 'focus', phase_length_s: 1500,
  ends_at: '2026-10-26T10:10:00.000Z', remaining_s: null,
  today: { rows: [], now: null, next: [] },
  ...o,
})

const view = (o: Partial<ShareView> = {}): ShareView => ({
  v: 1, generated_at: '2026-10-26T10:00:00.000Z', poll_seconds: 15, day: '2026-10-26', days: 7,
  focus: null, lists: [], calendars: [], events: [], events_more: 0,
  ...o,
})

const event = (o: Partial<ShareEvent> = {}): ShareEvent => ({
  title: 'Standup', start: '2026-10-26T13:30:00.000Z', end: '2026-10-26T13:45:00.000Z',
  all_day: false, calendar: 0, private: false,
  ...o,
})

// The suite runs under America/New_York (vite.config). The agenda tests below
// need the zones on either side of it, and a viewer's zone is process-wide, so
// it is switched for the length of one callback and always put back.
const home = process.env.TZ
function inZone<T>(tz: string, fn: () => T): T {
  process.env.TZ = tz
  try {
    return fn()
  } finally {
    process.env.TZ = home
  }
}
afterEach(() => { process.env.TZ = home })

describe('skewOf', () => {
  it('is server time minus device time', () => {
    expect(skewOf('2026-10-26T10:00:00.000Z', T0 - 3 * HOUR)).toBe(3 * HOUR)
    expect(skewOf('2026-10-26T10:00:00.000Z', T0 + 3 * HOUR)).toBe(-3 * HOUR)
  })
})

describe('remainingS', () => {
  it('counts down to a running phase\'s end', () => {
    expect(remainingS(focus(), T0, 0)).toBe(600)
    expect(remainingS(focus(), T0 + 90_000, 0)).toBe(510)
  })

  it('floors a fraction of a second, so the clock never shows a second it no longer has', () => {
    expect(remainingS(focus(), T0 + 500, 0)).toBe(599)
  })

  it('clamps at zero once the end has passed', () => {
    expect(remainingS(focus(), T0 + 20 * 60_000, 0)).toBe(0)
  })

  it('reads the server\'s clock when the device is three hours off', () => {
    // Device three hours fast: it reads 13:00 when the server's clock reads 10:00.
    const fast = skewOf('2026-10-26T10:00:00.000Z', T0 + 3 * HOUR)
    expect(remainingS(focus(), T0 + 3 * HOUR, fast)).toBe(600)
    expect(remainingS(focus(), T0 + 3 * HOUR + 300_000, fast)).toBe(300)
    // Device three hours slow.
    const slow = skewOf('2026-10-26T10:00:00.000Z', T0 - 3 * HOUR)
    expect(remainingS(focus(), T0 - 3 * HOUR + 300_000, slow)).toBe(300)
  })

  it('freezes while paused', () => {
    const f = focus({ state: 'paused', ends_at: null, remaining_s: 421 })
    expect(remainingS(f, T0, 0)).toBe(421)
    expect(remainingS(f, T0 + HOUR, 0)).toBe(421)
  })

  it('has no clock between phases or when idle', () => {
    expect(remainingS(focus({ state: 'between', ends_at: null }), T0, 0)).toBeNull()
    expect(remainingS(focus({ state: 'idle', ends_at: null, phase: null }), T0, 0)).toBeNull()
  })
})

describe('localState', () => {
  it('flips a finished phase to between without waiting for a poll', () => {
    expect(localState(focus(), T0 + 599_000, 0)).toBe('focusing')
    expect(localState(focus(), T0 + 600_000, 0)).toBe('between')
    expect(localState(focus({ state: 'break', phase: 'break' }), T0 + 601_000, 0)).toBe('between')
  })

  it('judges the end on the server\'s clock', () => {
    const fast = 3 * HOUR
    // The device reads 13:09:59 when the server reads 10:09:59 — a second short.
    expect(localState(focus(), T0 + 599_000 + fast, -fast)).toBe('focusing')
    expect(localState(focus(), T0 + 600_000 + fast, -fast)).toBe('between')
  })

  it('leaves the other states as they are', () => {
    const paused = focus({ state: 'paused', ends_at: null, remaining_s: 10 })
    expect(localState(paused, T0 + HOUR, 0)).toBe('paused')
    expect(localState(focus({ state: 'idle', ends_at: null }), T0, 0)).toBe('idle')
  })
})

describe('progress', () => {
  it('is the elapsed share of the phase', () => {
    expect(progress(focus({ phase_length_s: 600 }), T0, 0)).toBe(0)
    expect(progress(focus({ phase_length_s: 1200 }), T0, 0)).toBe(0.5)
  })

  it('is 1 once the phase is over and 0 when idle or unmeasured', () => {
    expect(progress(focus(), T0 + HOUR, 0)).toBe(1)
    expect(progress(focus({ state: 'idle', ends_at: null }), T0, 0)).toBe(0)
    expect(progress(focus({ phase_length_s: null }), T0, 0)).toBe(0)
  })

  it('stays within 0..1', () => {
    // A phase shorter than the time left on it, as a stale length would give.
    expect(progress(focus({ phase_length_s: 60 }), T0, 0)).toBe(0)
  })
})

describe('nextPollDelay', () => {
  const base = { failures: 0, hidden: false, nowMs: T0, skewMs: 0 }

  it('does not poll a hidden tab', () => {
    expect(nextPollDelay({ ...base, view: view(), hidden: true })).toBeNull()
    expect(nextPollDelay({ ...base, view: view(), hidden: true, failures: 3 })).toBeNull()
  })

  it('backs off 5, 10, 20, 40 and then holds at 60 seconds', () => {
    const delays = [1, 2, 3, 4, 5, 6, 9].map(failures =>
      nextPollDelay({ ...base, view: view(), failures }))
    expect(delays).toEqual([5_000, 10_000, 20_000, 40_000, 60_000, 60_000, 60_000])
  })

  it('retries soon when there is no view yet', () => {
    expect(nextPollDelay({ ...base, view: null })).toBe(5_000)
  })

  it('waits the server\'s poll interval', () => {
    expect(nextPollDelay({ ...base, view: view({ poll_seconds: 15 }) })).toBe(15_000)
    expect(nextPollDelay({ ...base, view: view({ poll_seconds: 30 }) })).toBe(30_000)
  })

  it('asks again two seconds after a running phase ends, when that is sooner', () => {
    const v = view({ poll_seconds: 30, focus: focus({ ends_at: '2026-10-26T10:00:10.000Z' }) })
    expect(nextPollDelay({ ...base, view: v })).toBe(12_000)
    // A phase that ends later than the interval does not stretch it.
    const far = view({ poll_seconds: 15, focus: focus() })
    expect(nextPollDelay({ ...base, view: far })).toBe(15_000)
  })

  it('measures that end on the server\'s clock', () => {
    const v = view({ poll_seconds: 30, focus: focus({ ends_at: '2026-10-26T10:00:10.000Z' }) })
    expect(nextPollDelay({ ...base, view: v, nowMs: T0 + 3 * HOUR, skewMs: -3 * HOUR })).toBe(12_000)
  })

  it('does not shorten for a phase that has already ended', () => {
    const v = view({ poll_seconds: 15, focus: focus({ ends_at: '2026-10-26T09:59:00.000Z' }) })
    expect(nextPollDelay({ ...base, view: v })).toBe(15_000)
  })

  it('never goes under two seconds', () => {
    const v = view({ poll_seconds: 30, focus: focus({ ends_at: '2026-10-26T09:59:59.500Z' }) })
    expect(nextPollDelay({ ...base, view: v })).toBe(2_000)
    expect(nextPollDelay({ ...base, view: view({ poll_seconds: 1 }) })).toBe(2_000)
  })

  it('does not shorten for a paused clock', () => {
    const v = view({ focus: focus({ state: 'paused', ends_at: null, remaining_s: 5 }) })
    expect(nextPollDelay({ ...base, view: v })).toBe(15_000)
  })
})

describe('isStale', () => {
  it('is two minutes at the usual interval', () => {
    const v = view({ poll_seconds: 15 })
    expect(isStale(T0, v, T0 + 120_000)).toBe(false)
    expect(isStale(T0, v, T0 + 120_001)).toBe(true)
  })

  it('scales with a slow interval', () => {
    const v = view({ poll_seconds: 60 })
    expect(isStale(T0, v, T0 + 150_000)).toBe(false)
    expect(isStale(T0, v, T0 + 150_001)).toBe(true)
  })

  it('is false before anything has been fetched', () => {
    expect(isStale(null, view(), T0 + HOUR)).toBe(false)
    expect(isStale(T0, null, T0 + HOUR)).toBe(false)
  })
})

describe('agendaDays', () => {
  it('starts at the day given and runs for as many days as asked', () => {
    expect(agendaDays('2026-10-26', 7)).toEqual([
      '2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29',
      '2026-10-30', '2026-10-31', '2026-11-01',
    ])
    expect(agendaDays('2026-10-26', 1)).toEqual(['2026-10-26'])
    expect(agendaDays('2026-10-26', 28)).toHaveLength(28)
  })

  it('does not skip or repeat a day across a clock change', () => {
    // New York falls back on 2026-11-01.
    expect(agendaDays('2026-10-30', 4)).toEqual(
      ['2026-10-30', '2026-10-31', '2026-11-01', '2026-11-02'])
  })

  it('crosses a month and a year', () => {
    expect(agendaDays('2026-12-30', 3)).toEqual(['2026-12-30', '2026-12-31', '2027-01-01'])
  })
})

describe('fmtDayLabel', () => {
  it('names today and tomorrow and dates the rest', () => {
    expect(fmtDayLabel('2026-10-26', '2026-10-26', 'en-US')).toBe('today')
    expect(fmtDayLabel('2026-10-27', '2026-10-26', 'en-US')).toBe('tomorrow')
    expect(fmtDayLabel('2026-10-28', '2026-10-26', 'en-US')).toBe('Wednesday, October 28')
  })

  it('follows the locale', () => {
    expect(fmtDayLabel('2026-10-28', '2026-10-26', 'de-DE')).toBe('Mittwoch, 28. Oktober')
  })

  it('calls the day after a month end tomorrow', () => {
    expect(fmtDayLabel('2026-11-01', '2026-10-31', 'en-US')).toBe('tomorrow')
  })
})

describe('fmtTime', () => {
  it('follows the viewer\'s 12/24-hour convention through the locale', () => {
    // 17:30Z is 13:30 in New York.
    expect(fmtTime('2026-10-26T17:30:00.000Z', 'en-US')).toMatch(/^1:30\s?PM$/)
    expect(fmtTime('2026-10-26T17:30:00.000Z', 'de-DE')).toBe('13:30')
  })
})

describe('ongoingEvent', () => {
  const now = Date.parse('2026-10-26T13:40:00.000Z')

  it('finds the timed event the moment falls inside', () => {
    expect(ongoingEvent([event()], now)?.title).toBe('Standup')
  })

  it('treats the end as exclusive and the start as inclusive', () => {
    expect(ongoingEvent([event()], Date.parse('2026-10-26T13:45:00.000Z'))).toBeNull()
    expect(ongoingEvent([event()], Date.parse('2026-10-26T13:30:00.000Z'))?.title).toBe('Standup')
  })

  it('ignores all-day events and events with no end', () => {
    const day = event({ all_day: true, start: '2026-10-26', end: '2026-10-27' })
    expect(ongoingEvent([day, event({ end: null })], now)).toBeNull()
  })

  it('takes the earliest start when several overlap, whatever the order', () => {
    const early = event({ title: 'Early', start: '2026-10-26T13:00:00.000Z' })
    const late = event({ title: 'Late', start: '2026-10-26T13:35:00.000Z' })
    expect(ongoingEvent([late, early], now)?.title).toBe('Early')
  })

  it('returns null for no events', () => {
    expect(ongoingEvent([], now)).toBeNull()
  })
})

describe('toBucket', () => {
  it('marks an all-day event\'s start and end as dates, and nothing else', () => {
    expect(toBucket(event({ all_day: true, start: '2026-10-27', end: '2026-10-30' })))
      .toMatchObject({ start_is_date: true, end_is_date: true, title: 'Standup' })
    expect(toBucket(event())).toMatchObject({ start_is_date: false, end_is_date: false })
  })
})

describe('bucketing share events', () => {
  const bucket = (events: ShareEvent[], days: string[]) =>
    bucketByDay(events.map(toBucket), days.map(d => new Date(`${d}T00:00`)))
  const keys = (m: Map<string, unknown>) => [...m.keys()].sort()

  it('puts a 03:00Z event on the previous local day under New York', () => {
    const m = bucket([event({ start: '2026-10-27T03:00:00.000Z', end: '2026-10-27T04:00:00.000Z' })],
      agendaDays('2026-10-26', 7))
    expect(keys(m)).toEqual(['2026-10-26'])
  })

  it('covers each date of an all-day span, ending before the exclusive end', () => {
    const m = bucket([event({ all_day: true, start: '2026-10-27', end: '2026-10-30' })],
      agendaDays('2026-10-26', 7))
    expect(keys(m)).toEqual(['2026-10-27', '2026-10-28', '2026-10-29'])
    expect(m.get('2026-10-27')![0].cont).toBeUndefined()
    expect(m.get('2026-10-28')![0].cont).toBe(true)
  })

  it('shows a timed span as continued on its later days', () => {
    const m = bucket([event({ start: '2026-10-27T22:00:00.000Z', end: '2026-10-28T14:00:00.000Z' })],
      agendaDays('2026-10-26', 7))
    expect(keys(m)).toEqual(['2026-10-27', '2026-10-28'])
    expect(m.get('2026-10-27')![0].cont).toBeUndefined()
    expect(m.get('2026-10-28')![0].cont).toBe(true)
  })

  it('keeps the share fields on what it returns', () => {
    const m = bucket([event({ private: true, title: '' })], agendaDays('2026-10-26', 7))
    expect(m.get('2026-10-26')![0]).toMatchObject({ private: true, title: '', calendar: 0 })
  })
})

// The agenda's days are the VIEWER's local days (the server widens its window by
// a day on each side so they are all covered). Starting from the owner's `day`
// would put a far-east viewer's tomorrow under "today" and drop a far-west
// viewer's evening altogether.
describe('the agenda in the viewer\'s own zone', () => {
  // 2026-10-26 22:00Z: it is already the 27th in Auckland (UTC+13) and still
  // the 26th in Honolulu (UTC-10), and the owner (say Berlin) reads the 26th.
  const nowMs = Date.parse('2026-10-26T22:00:00.000Z')

  it('starts a far-east viewer\'s agenda on their own, later, date', () => {
    inZone('Pacific/Auckland', () => {
      const today = ymd(new Date(nowMs))
      expect(today).toBe('2026-10-27')
      const days = agendaDays(today, 7)
      expect(days[0]).toBe('2026-10-27')
      // 23:30Z on the owner's 26th is 12:30 on the 27th in Auckland: today.
      const m = bucket(
        [event({ title: 'Tonight', start: '2026-10-26T23:30:00.000Z', end: '2026-10-27T00:30:00.000Z' }),
          event({ title: 'Seen yesterday', start: '2026-10-26T09:00:00.000Z', end: '2026-10-26T10:00:00.000Z' })],
        days)
      expect(keys(m)).toEqual(['2026-10-27'])
      expect(m.get('2026-10-27')!.map(e => e.title)).toEqual(['Tonight'])
      expect(fmtDayLabel('2026-10-27', today, 'en-US')).toBe('today')
    })
  })

  it('keeps a far-west viewer\'s agenda on their own, earlier, date', () => {
    inZone('Pacific/Honolulu', () => {
      const today = ymd(new Date(nowMs))
      expect(today).toBe('2026-10-26')
      const days = agendaDays(today, 7)
      // 02:00Z on the 27th is 16:00 on the 26th in Honolulu: still today.
      const m = bucket(
        [event({ title: 'This afternoon', start: '2026-10-27T02:00:00.000Z', end: '2026-10-27T03:00:00.000Z' }),
          event({ title: 'Last night', start: '2026-10-26T05:00:00.000Z', end: '2026-10-26T06:00:00.000Z' })],
        days)
      expect(keys(m)).toEqual(['2026-10-26'])
      expect(m.get('2026-10-26')!.map(e => e.title)).toEqual(['This afternoon'])
    })
  })

  it('reaches the last day of the horizon in either zone', () => {
    for (const tz of ['Pacific/Auckland', 'Pacific/Honolulu']) {
      inZone(tz, () => {
        const today = ymd(new Date(nowMs))
        const days = agendaDays(today, 7)
        // The last agenda day, at local noon, as an instant.
        const noon = new Date(`${days[6]}T12:00`).toISOString()
        const m = bucket([event({ start: noon, end: null })], days)
        expect(keys(m)).toEqual([days[6]])
      })
    }
  })

  function bucket(events: ShareEvent[], days: string[]) {
    return bucketByDay(events.map(toBucket), days.map(d => new Date(`${d}T00:00`)))
  }
  function keys(m: Map<string, unknown>) { return [...m.keys()].sort() }
})
