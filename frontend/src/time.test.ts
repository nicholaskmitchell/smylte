import { describe, expect, it } from 'vitest'
import {
  DEFAULT_TIME_FORMAT, fmtClock, fmtDue, fmtWhen, inputLang, isTimeFormat,
  nextTimeFormat, timeFormatLabel,
} from './time'

// The suite runs under a fixed TZ (vite.config sets it) and these assertions
// only ever look at the clock part, so a floating local datetime reads back as
// the wall time it names whatever the host's zone is.

describe('fmtClock', () => {
  it('renders 24-hour zero-padded and 12-hour with a meridiem', () => {
    expect(fmtClock('2026-07-11T09:05', '24h')).toBe('09:05')
    expect(fmtClock('2026-07-11T14:05', '24h')).toBe('14:05')
    expect(fmtClock('2026-07-11T09:05', '12h')).toMatch(/^9:05\s?AM$/)
    expect(fmtClock('2026-07-11T14:05', '12h')).toMatch(/^2:05\s?PM$/)
  })

  it('gets midnight and noon right in both formats', () => {
    // The two the hour12 flag is easiest to get wrong: 00:00 must not read as
    // "0:00 AM" on a 12-hour clock, and 12:00 must not read as "00:00" on a
    // 24-hour one.
    expect(fmtClock('2026-07-11T00:00', '24h')).toBe('00:00')
    expect(fmtClock('2026-07-11T12:00', '24h')).toBe('12:00')
    expect(fmtClock('2026-07-11T00:00', '12h')).toMatch(/^12:00\s?AM$/)
    expect(fmtClock('2026-07-11T12:00', '12h')).toMatch(/^12:00\s?PM$/)
  })

  it('echoes garbage rather than rendering NaN', () => {
    expect(fmtClock('not-a-date', '24h')).toBe('not-a-date')
  })
})

describe('fmtDue', () => {
  it('is empty for null and echoes garbage instead of NaN', () => {
    expect(fmtDue(null, false, '24h')).toBe('')
    expect(fmtDue('not-a-date', false, '24h')).toBe('not-a-date')
  })

  it('omits the time for an all-day due whatever the clock is', () => {
    // An all-day due has no time to render, so the setting must not make one
    // appear — a bare date is the whole point of due_is_date.
    for (const f of ['12h', '24h'] as const) {
      const s = fmtDue('2026-07-11', true, f)
      expect(s).not.toMatch(/\d\d?:\d\d/)
      expect(s).not.toMatch(/[AP]M/i)
    }
  })

  it('carries the time for a timed due, in the chosen clock', () => {
    expect(fmtDue('2026-07-11T14:05', false, '24h')).toMatch(/14:05/)
    expect(fmtDue('2026-07-11T14:05', false, '24h')).not.toMatch(/[AP]M/i)
    expect(fmtDue('2026-07-11T14:05', false, '12h')).toMatch(/2:05\s?PM/)
  })
})

describe('fmtWhen', () => {
  it('carries weekday, date and the chosen clock', () => {
    const s = fmtWhen('2026-07-11T14:05', '24h')
    expect(s).toMatch(/Sat/)
    expect(s).toMatch(/14:05/)
    expect(fmtWhen('2026-07-11T14:05', '12h')).toMatch(/2:05\s?PM/)
  })

  it('echoes garbage rather than rendering NaN', () => {
    expect(fmtWhen('not-a-date', '12h')).toBe('not-a-date')
  })
})

describe('the stored value', () => {
  it('accepts only the two formats — the blob is hand-editable', () => {
    expect(isTimeFormat('12h')).toBe(true)
    expect(isTimeFormat('24h')).toBe(true)
    for (const bad of ['24', 'H:mm', '', null, undefined, 24, {}]) {
      expect(isTimeFormat(bad)).toBe(false)
    }
  })

  it('defaults to what the app did before this was settable', () => {
    expect(DEFAULT_TIME_FORMAT).toBe('12h')
  })

  it('cycles between the two and labels each', () => {
    expect(nextTimeFormat('12h')).toBe('24h')
    expect(nextTimeFormat('24h')).toBe('12h')
    expect(timeFormatLabel('12h')).toBe('12-hour')
    expect(timeFormatLabel('24h')).toBe('24-hour')
  })
})

describe('inputLang', () => {
  it('picks a locale whose clock matches the setting', () => {
    // Native pickers read `lang`, not our formatters — en-GB is 24-hour and
    // en-US is 12-hour, which is the whole trick.
    expect(inputLang('24h')).toBe('en-GB')
    expect(inputLang('12h')).toBe('en-US')
  })
})
