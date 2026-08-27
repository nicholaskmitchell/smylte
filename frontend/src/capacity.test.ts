import { describe, expect, it } from 'vitest'
import {
  MAX_CAPACITY, capacityInput, parseCapacity, sanitizeCapacityByWeekday,
} from './capacity'

/** A fixed clock, so a stop time is decidable. 09:00 on a Monday. */
const NINE_AM = new Date(2026, 7, 24, 9, 0, 0)

describe('parseCapacity — spans', () => {
  it('reads the ways a length of time gets typed', () => {
    expect(parseCapacity('5h', NINE_AM)).toBe(300)
    expect(parseCapacity('5h30', NINE_AM)).toBe(330)
    expect(parseCapacity('5h 30m', NINE_AM)).toBe(330)
    expect(parseCapacity('90m', NINE_AM)).toBe(90)
    expect(parseCapacity('1.5h', NINE_AM)).toBe(90)
    expect(parseCapacity('2 hours', NINE_AM)).toBe(120)
    expect(parseCapacity('45 mins', NINE_AM)).toBe(45)
  })

  it('reads a bare number as MINUTES', () => {
    // The unit the wire speaks, and what a "300" typed into a field almost
    // certainly means. Checked before the span grammar so it cannot be read as
    // three hundred hours by a regex whose unit groups are both optional.
    expect(parseCapacity('300', NINE_AM)).toBe(300)
    expect(parseCapacity('0', NINE_AM)).toBe(0)
  })

  it('does not consult the clock for a span', () => {
    // "5h" means five hours whenever it is said. Only a stop time needs to know
    // when now is, which is the whole reason `now` is a parameter rather than
    // something this module reaches for.
    const evening = new Date(2026, 7, 24, 22, 0, 0)
    expect(parseCapacity('5h', evening)).toBe(parseCapacity('5h', NINE_AM))
  })
})

describe('parseCapacity — stop times', () => {
  it('measures from the clock it is handed', () => {
    expect(parseCapacity('until 6pm', NINE_AM)).toBe(9 * 60)
    expect(parseCapacity('till 18:00', NINE_AM)).toBe(9 * 60)
    expect(parseCapacity('to 5.30pm', NINE_AM)).toBe(8 * 60 + 30)
    expect(parseCapacity('6pm', NINE_AM)).toBe(9 * 60)
  })

  it('reads a small bare hour as the evening', () => {
    // The module's one inference, and it is bounded: nobody states a working
    // day that ends before breakfast, so 1..7 mean the afternoon. 8 through 23
    // are taken at face value, so only the genuinely ambiguous half of the
    // clock is guessed at.
    expect(parseCapacity('until 6', NINE_AM)).toBe(9 * 60)
    expect(parseCapacity('until 17', NINE_AM)).toBe(8 * 60)
  })

  it('answers nothing for a stop time that has already gone', () => {
    // "I stop at 6" typed at 7pm is somebody correcting a day that already ran
    // over. Reading it as tomorrow would silently book them twenty-three hours,
    // which is the worst available answer; null leaves the field alone and lets
    // them say what they meant.
    const sevenPm = new Date(2026, 7, 24, 19, 0, 0)
    expect(parseCapacity('until 6pm', sevenPm)).toBeNull()
    expect(parseCapacity('until 6pm', new Date(2026, 7, 24, 18, 0, 0))).toBeNull()
  })

  it('refuses a clock that is not one', () => {
    expect(parseCapacity('until 25:00', NINE_AM)).toBeNull()
    expect(parseCapacity('until 6:99', NINE_AM)).toBeNull()
    expect(parseCapacity('until 13pm', NINE_AM)).toBeNull()
  })
})

describe('parseCapacity — refusing', () => {
  it('says nothing rather than guessing', () => {
    // A line this cannot read costs a retype. A line it reads WRONGLY books a
    // day of the wrong length and says nothing about it, so every uncertain
    // case answers null.
    for (const junk of ['', '   ', 'soon', 'a while', 'h', 'm', 'abc', '5x', '-3']) {
      expect(parseCapacity(junk, NINE_AM), junk).toBeNull()
    }
  })

  it('never reads garbage as a capacity of zero', () => {
    // Both unit groups in the span grammar are optional, so the regex matches
    // the empty string — and zero IS a real capacity ("not working today"), so
    // arriving at it by accident is worse than refusing.
    expect(parseCapacity('h', NINE_AM)).toBeNull()
    expect(parseCapacity('0', NINE_AM)).toBe(0)
  })

  it('holds a capacity to a day', () => {
    expect(parseCapacity('99h', NINE_AM)).toBe(MAX_CAPACITY)
    expect(parseCapacity('999999', NINE_AM)).toBe(MAX_CAPACITY)
  })
})

describe('sanitizeCapacityByWeekday', () => {
  it('keeps the weekday names it knows and drops the rest', () => {
    expect(sanitizeCapacityByWeekday({ mon: 300, funday: 60, fri: 180 }))
      .toEqual({ mon: 300, fri: 180 })
  })

  it('treats the blob as hand-edited', () => {
    // Every settings value is, and this one filters rather than rejects so a map
    // from a newer client still contributes what it can.
    expect(sanitizeCapacityByWeekday({
      mon: '300', tue: null, wed: -5, thu: 99999, fri: NaN, sat: 120,
    })).toEqual({ sat: 120 })
    expect(sanitizeCapacityByWeekday(null)).toEqual({})
    expect(sanitizeCapacityByWeekday('mon')).toEqual({})
    expect(sanitizeCapacityByWeekday([1, 2])).toEqual({})
  })

  it('keeps a deliberate zero', () => {
    // "I do not work Sundays" is a statement, and it has to survive every falsy
    // check between the settings blob and the read.
    expect(sanitizeCapacityByWeekday({ sun: 0 })).toEqual({ sun: 0 })
  })
})

describe('capacityInput', () => {
  it('says the number back the way a person would', () => {
    // It used to print a bare integer for anything that was not a whole hour,
    // so typing "until 6pm" at half past four left the field reading `89` —
    // correct, and useless: a time went in and an unlabelled number came back.
    expect(capacityInput(300)).toBe('5h')
    expect(capacityInput(60)).toBe('1h')
    expect(capacityInput(89)).toBe('1h 29m')
    expect(capacityInput(330)).toBe('5h 30m')
    expect(capacityInput(45)).toBe('45m')
    expect(capacityInput(0)).toBe('0m')
    expect(capacityInput(null)).toBe('')
  })

  it('round-trips through the parser', () => {
    // Every shape `capacityInput` produces has to read back as the number it
    // came from, because it IS the field's value — not a label beside one.
    for (const m of [0, 1, 45, 59, 60, 89, 90, 300, 330, 1439, 1440]) {
      expect(parseCapacity(capacityInput(m), NINE_AM), String(m)).toBe(m)
    }
  })
})


describe('a SETTING must not take a statement about today', () => {
  const at1630 = new Date('2026-08-25T16:30:00')
  const at0900 = new Date('2026-08-25T09:00:00')

  it('refuses a stop time when the caller asks it to', () => {
    // CapacitySection's own header says a stop time is deliberately NOT accepted
    // there: "until 6pm" is a statement about today, and a default that meant
    // six hours on Monday and two on Friday afternoon would be a setting whose
    // value depended on when you last opened Settings.
    //
    // The field called the shared parser, which has the stop grammar, so it took
    // exactly that spelling — and stored the interval from whenever Settings
    // happened to be open, as the ACCOUNT-WIDE default for every weekday.
    for (const line of ['until 6pm', 'til 18:00', 'to 6pm', '18:00', '6pm']) {
      expect(parseCapacity(line, at1630, { stopTime: false }),
        `${line} must not read as a span`).toBeNull()
    }
  })

  it('refuses rather than falling through to the span grammar', () => {
    // The failure worth naming: "until 6pm" quietly becoming "6 hours" would be
    // a WRONG reading, which this module's docstring calls the one outcome worse
    // than no reading.
    expect(parseCapacity('until 6pm', at1630, { stopTime: false })).toBeNull()
    expect(parseCapacity('6pm', at1630, { stopTime: false })).toBeNull()
  })

  it('still reads a span, and reads it the same at any hour', () => {
    for (const now of [at1630, at0900]) {
      expect(parseCapacity('5h', now, { stopTime: false })).toBe(300)
      expect(parseCapacity('1h 30m', now, { stopTime: false })).toBe(90)
      expect(parseCapacity('300', now, { stopTime: false })).toBe(300)
    }
  })

  it("leaves the day's own control alone — it takes a stop time by design", () => {
    // Default is unchanged, and it IS clock-dependent, which is correct there:
    // that control is a statement about today.
    expect(parseCapacity('until 6pm', at1630)).toBe(90)
    expect(parseCapacity('until 6pm', at0900)).toBe(540)
  })
})
