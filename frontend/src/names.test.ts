// Weekday and month names come out of the platform, in the app's language, in
// the order the caller asked for.
//
// The order is what these mostly guard. Every name list here is indexed by
// something — `Date#getDay`, the availability map's "0".."6" keys, a position in
// `HABIT_DAYS` — and two of those conventions disagree about where a week
// starts. A rotation by one is invisible in a screenshot and wrong on exactly
// one weekday, which is the kind of bug that ships.

import { describe, expect, it } from 'vitest'
import { habitDayLabel, monthNames, weekdayNames } from './names'

describe('weekdayNames', () => {
  it('starts on Monday by default — the order the server writes days in', () => {
    expect(weekdayNames('en')).toEqual([
      'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'])
  })

  it('starts on Sunday when asked, for callers indexing by Date#getDay', () => {
    expect(weekdayNames('en', 'short', 'sun')).toEqual([
      'Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'])
  })

  // The reference week is noon UTC precisely so this holds. The unit suite runs
  // in America/New_York (vitest.config.ts), where a midnight-UTC Monday is
  // Sunday evening — so a naive reference date would rotate every list here by
  // one for every viewer west of Greenwich, and pass on a CI box set to UTC.
  it('is not shifted by the viewer being behind UTC', () => {
    expect(new Date().getTimezoneOffset()).toBeGreaterThan(0)
    expect(weekdayNames('en')[0]).toBe('Monday')
    expect(weekdayNames('en', 'short', 'sun')[0]).toBe('Sun')
  })

  it('speaks German', () => {
    expect(weekdayNames('de')[0]).toBe('Montag')
    expect(weekdayNames('de')[2]).toBe('Mittwoch')
    expect(weekdayNames('de')[6]).toBe('Sonntag')
  })

  // The abbreviation is CLDR's, not the first three letters of the long name —
  // that is the whole reason these come from Intl. German shortens Mittwoch to
  // "Mi", where slicing would have produced "Mit". Whether ICU writes the
  // trailing point varies by version and is not what this is pinning.
  it('abbreviates the way the language does, not by slicing', () => {
    expect(weekdayNames('de', 'short')[2]).toMatch(/^Mi\.?$/)
    expect(weekdayNames('en', 'short')[2]).toBe('Wed')
  })

  it('hands back the same array for the same question', () => {
    expect(weekdayNames('en', 'short')).toBe(weekdayNames('en', 'short'))
    expect(weekdayNames('en', 'short')).not.toBe(weekdayNames('en', 'short', 'sun'))
  })
})

describe('monthNames', () => {
  it('is indexed the way Date#getMonth counts', () => {
    expect(monthNames('en')[0]).toBe('January')
    expect(monthNames('en')[11]).toBe('December')
  })

  it('speaks German', () => {
    expect(monthNames('de')[0]).toBe('Januar')
    expect(monthNames('de')[9]).toBe('Oktober')
  })
})

describe('habitDayLabel', () => {
  it('reads a HABIT_DAYS token as the day it names', () => {
    expect(habitDayLabel('mon', 'en')).toBe('Mon')
    expect(habitDayLabel('wed', 'en')).toBe('Wed')
    expect(habitDayLabel('sun', 'en')).toBe('Sun')
  })

  // The English labels are exactly what the old `d[0].toUpperCase() + d.slice(1)`
  // produced, which is why moving the habit chips onto this changed nothing on
  // an English screen — and why the tests that name those chips still pass.
  it('matches what capitalising the token used to give, in English', () => {
    for (const d of ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']) {
      expect(habitDayLabel(d, 'en')).toBe(d[0].toUpperCase() + d.slice(1))
    }
  })

  it('speaks German', () => {
    expect(habitDayLabel('wed', 'de')).toMatch(/^Mi\.?$/)
  })

  // A token nothing on the wire should produce. It gets the old capitalisation
  // rather than a guessed weekday: inventing a day for an unknown name is how
  // the two sides come to disagree about what "wed" means.
  it('does not invent a weekday for a token it does not know', () => {
    expect(habitDayLabel('caturday', 'en')).toBe('Caturday')
    expect(habitDayLabel('', 'en')).toBe('')
  })
})
