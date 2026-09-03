import { describe, expect, it } from 'vitest'
import {
  DEFAULT_TIME_FORMAT, fmtClock, fmtCountdown, fmtDue, fmtDuration, fmtWhen, inputLang,
  isTimeFormat, nextTimeFormat, timeFormatKey,
} from './time'

describe('fmtCountdown', () => {
  it('spells minutes and seconds, and hours only once there are any', () => {
    expect(fmtCountdown(1499)).toBe('24:59')
    expect(fmtCountdown(7)).toBe('0:07')
    expect(fmtCountdown(60)).toBe('1:00')
    expect(fmtCountdown(3723)).toBe('1:02:03')
    expect(fmtCountdown(3600)).toBe('1:00:00')
  })

  it('floors rather than rounds, and never goes below zero', () => {
    // A second the phase no longer has must not be shown; a phase past its end
    // reads 0:00 rather than a negative clock.
    expect(fmtCountdown(0.6)).toBe('0:00')
    expect(fmtCountdown(-3)).toBe('0:00')
    expect(fmtCountdown(0)).toBe('0:00')
  })
})

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
    // Catalogue keys, not text — see `timeFormatKey`.
    expect(timeFormatKey('12h')).toBe('clock.12h')
    expect(timeFormatKey('24h')).toBe('clock.24h')
  })
})

describe('inputLang', () => {
  it('picks a locale whose clock matches the setting', () => {
    // Native pickers read `lang`, not our formatters — en-GB is 24-hour and
    // en-US is 12-hour, which is the whole trick.
    expect(inputLang('24h')).toBe('en-GB')
    expect(inputLang('12h')).toBe('en-US')
  })

  it("carries the app's language, so the picker names months in it", () => {
    // The same attribute that chooses the clock also chooses the calendar
    // popup's month names. German everywhere and "September" in the one popup
    // would be the seam showing.
    expect(inputLang('24h', 'de')).toBe('de')
  })

  it('asks outright for a clock no region of the language keeps', () => {
    // Every German-speaking country runs a 24-hour clock, so unlike English
    // there is no region to pick for 12h — only the -u-hc- extension says it.
    // Where a browser ignores extensions the fallback is German's own 24-hour
    // clock, which is a sane thing to be handed rather than a broken one.
    expect(inputLang('12h', 'de')).toBe('de-u-hc-h12')
  })

  it('defaults to the two tags it always returned', () => {
    // Callers and tests that predate the Language setting pass one argument.
    // English is the one language here that needs no extension, which is also
    // why it degrades correctly in a browser that honours none.
    expect(inputLang('24h', 'en')).toBe(inputLang('24h'))
    expect(inputLang('12h', 'en')).toBe(inputLang('12h'))
  })
})

describe('the locale argument', () => {
  // Every formatter takes one, and every formatter treats omitting it as
  // "format for the device" — which is what these calls passed before the
  // Language setting existed. That is what lets a call site be threaded one at
  // a time without a flag day.
  it('is optional, and omitting it means the device', () => {
    expect(fmtClock('2024-02-05T14:05:00', '24h')).toBe(
      fmtClock('2024-02-05T14:05:00', '24h', undefined))
    expect(fmtDue('2024-02-05T14:05:00', true, '24h')).toBe(
      fmtDue('2024-02-05T14:05:00', true, '24h', undefined))
    expect(fmtWhen('2024-02-05T14:05:00', '24h')).toBe(
      fmtWhen('2024-02-05T14:05:00', '24h', undefined))
  })

  it('reorders the date, not just the words in it', () => {
    // The reason this is a locale and not a lookup of month names: German
    // writes the day first and puts a point after it. A catalogue of translated
    // month names would have produced "Feb. 5" in German.
    expect(fmtDue('2024-02-05T00:00:00', true, '24h', 'de')).toBe('5. Feb.')
    expect(fmtDue('2024-02-05T00:00:00', true, '24h', 'en')).toBe('Feb 5')
  })

  it('does not let the locale overrule the clock setting', () => {
    // German is a 24-hour language and the setting still wins: the whole point
    // of `clockOpts` passing `hour12` explicitly is that the format is the
    // account's choice, not a property of the language it reads.
    expect(fmtClock('2024-02-05T14:05:00', '12h', 'de')).toMatch(/2:05/)
    expect(fmtClock('2024-02-05T14:05:00', '24h', 'de')).toBe('14:05')
  })
})

describe('fmtDuration', () => {
  it('spells a length of time in the compactest honest form', () => {
    expect(fmtDuration(45)).toBe('45m')
    expect(fmtDuration(60)).toBe('1h')
    expect(fmtDuration(90)).toBe('1h 30m')
    expect(fmtDuration(150)).toBe('2h 30m')
    // A whole hour drops the minutes: "2h 0m" says nothing the "2h" did not.
    expect(fmtDuration(120)).toBe('2h')
  })

  it('says zero rather than nothing', () => {
    // "0m" and "" are different facts and the running total turns on the
    // difference: a row deliberately estimated at nothing has been estimated,
    // and a row nobody has looked at has not. The empty string here would make
    // the second look like the first.
    expect(fmtDuration(0)).toBe('0m')
  })

  it("never puts the wire's clear sentinel on the screen", () => {
    // -1 means CLEAR on the wire (PatchDayEntryBody.estimate_minutes). It should
    // never reach a formatter, and if it does the answer is "0m" rather than
    // "-1m" — a protocol detail rendered as a duration is worse than a wrong
    // duration, because it reads as data.
    expect(fmtDuration(-1)).toBe('0m')
    expect(fmtDuration(-90)).toBe('0m')
  })

  it('does not consult the clock setting', () => {
    // The distinction this file is built on: 12- or 24-hour decides how an
    // INSTANT is named, and an hour and a half is an hour and a half either
    // way. `fmtDuration` takes no TimeFormat, which is the assertion — this
    // case exists so that adding one is a deliberate act with a test to change.
    expect(fmtDuration.length).toBe(1)
  })
})
