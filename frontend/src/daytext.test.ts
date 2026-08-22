import { describe, expect, it } from 'vitest'
import { parseEntry } from './daytext'
import { parseDate, ymd } from './util'

// A FIXED now, for every case that does not say otherwise: Friday 21 August
// 2026 at 10:00 local. Fixed because the module promises its reading never
// depends on the wall clock, and a suite that passed `new Date()` could not
// tell that promise from a coincidence. Friday because it is the one weekday
// that makes "friday" ambiguous — see the strictly-after case below.
const NOW = new Date(2026, 7, 21, 10, 0)

const parse = (text: string, now: Date = NOW) => parseEntry(text, now)

/** The whole shape, for the many cases that must come back untouched. */
const untouched = (text: string) => ({ summary: text, dueDate: '', dueTime: '', guessed: false })

describe('times', () => {
  it('reads the four self-marking forms', () => {
    // Self-marking: a colon or a meridiem says "clock" on its own, so these
    // need no introducer — only the position rule.
    expect(parse('standup 3pm')).toEqual({ summary: 'standup', dueDate: '', dueTime: '15:00', guessed: false })
    expect(parse('standup 3 pm')).toEqual({ summary: 'standup', dueDate: '', dueTime: '15:00', guessed: false })
    expect(parse('standup 3:30pm')).toEqual({ summary: 'standup', dueDate: '', dueTime: '15:30', guessed: false })
    expect(parse('standup 14:00')).toEqual({ summary: 'standup', dueDate: '', dueTime: '14:00', guessed: false })
  })

  it('reads a bare hour only when at or @ introduces it', () => {
    expect(parse('gym at 7')).toEqual({ summary: 'gym', dueDate: '', dueTime: '07:00', guessed: true })
    expect(parse('call mum @ 6')).toEqual({ summary: 'call mum', dueDate: '', dueTime: '18:00', guessed: true })
    // Glued, because "@6" is how people actually type it.
    expect(parse('call mum @6')).toEqual({ summary: 'call mum', dueDate: '', dueTime: '18:00', guessed: true })
    // The same digit with nothing introducing it is just a number.
    expect(parse('gym 7')).toEqual(untouched('gym 7'))
  })

  it('leaves no date behind when only a time was typed', () => {
    // Deliberate: the box belongs to a day that is already chosen, so inventing
    // a date here would silently overrule the day the user is planning.
    expect(parse('gym at 7').dueDate).toBe('')
  })

  it('accepts a minute only as exactly two digits, 00-59', () => {
    expect(parse('sync at 7:05pm').dueTime).toBe('19:05')
    // "9:5" is not a time; the colon-with-one-digit shape is far more often a
    // score, a version or a ratio.
    expect(parse('meeting at 9:5')).toEqual(untouched('meeting at 9:5'))
    expect(parse('gym at 7:60')).toEqual(untouched('gym at 7:60'))
  })

  it('accepts an hour only in 0-23', () => {
    expect(parse('shift at 23').dueTime).toBe('23:00')
    expect(parse('gym at 25')).toEqual(untouched('gym at 25'))
    expect(parse('standup 25:00')).toEqual(untouched('standup 25:00'))
  })

  it('refuses a meridiem on an hour that cannot have one', () => {
    // "13pm" states two contradictory things. Picking one is repair work, and
    // repair work is how a parser ends up authoring a time nobody typed.
    expect(parse('gym at 13pm')).toEqual(untouched('gym at 13pm'))
  })

  it('gets noon and midnight right in both directions', () => {
    // The two the 12-hour wrap is easiest to get wrong: 12am is 00:00 and 12pm
    // is 12:00, not the other way round and not 24:00.
    expect(parse('party at 12am').dueTime).toBe('00:00')
    expect(parse('party at 12pm').dueTime).toBe('12:00')
    expect(parse('shift at 0').dueTime).toBe('00:00')
  })
})

describe('the meridiem table', () => {
  // Inferred: nothing in the line said which half of the day, so the table
  // chose and the result is marked as a guess.
  it.each([
    [1, '13:00'], [3, '15:00'], [6, '18:00'],
    [7, '07:00'], [9, '09:00'], [11, '11:00'],
    [12, '12:00'],
  ])('reads "at %i" as %s and marks it guessed', (hour, time) => {
    expect(parse(`gym at ${hour}`)).toEqual({ summary: 'gym', dueDate: '', dueTime: time, guessed: true })
  })

  // Stated: an hour outside 1-12 already names its own half of the day, so
  // nothing was inferred and nothing is flagged.
  it.each([[0, '00:00'], [13, '13:00'], [18, '18:00'], [23, '23:00']])(
    'reads "at %i" as %s with nothing guessed', (hour, time) => {
      expect(parse(`gym at ${hour}`)).toEqual({ summary: 'gym', dueDate: '', dueTime: time, guessed: false })
    })

  it('applies the table to a colon time too, and flags it', () => {
    // "9:30" states the minute but still not the half of the day, so the same
    // table runs and the same flag goes up. The pair below is what shows the
    // flag is keyed to the hour VALUE and not to how many digits were typed: a
    // zero-padded "07:00" is inferred exactly as a bare "9:30" is, because 7
    // and 9 are both in 1-11. Keying it to the value is the only rule that can
    // be stated without guessing at intent.
    expect(parse('standup 9:30')).toEqual({ summary: 'standup', dueDate: '', dueTime: '09:30', guessed: true })
    expect(parse('sync at 07:00')).toEqual({ summary: 'sync', dueDate: '', dueTime: '07:00', guessed: true })
    // Stated outright, so no guess.
    expect(parse('standup 14:00').guessed).toBe(false)
    expect(parse('standup 3:30pm').guessed).toBe(false)
  })

  it('does not move with the time of day it is run at', () => {
    // The property the whole module is built around: the same line read at
    // 03:00, 10:00 and 20:30 is the same entry. A table that leaned on "now" —
    // "3 must mean tomorrow, it is already 16:00" — could not be pinned by any
    // test, and would make one typed line mean two things in one afternoon.
    for (const hour of [0, 3, 10, 16, 20, 23]) {
      expect(parse('gym at 7', new Date(2026, 7, 21, hour, 30)).dueTime).toBe('07:00')
      expect(parse('gym at 3', new Date(2026, 7, 21, hour, 30)).dueTime).toBe('15:00')
    }
  })
})

describe('dates', () => {
  it('reads today, tomorrow and tonight', () => {
    expect(parse('groceries today')).toEqual({ summary: 'groceries', dueDate: '2026-08-21', dueTime: '', guessed: false })
    expect(parse('dentist tomorrow')).toEqual({ summary: 'dentist', dueDate: '2026-08-22', dueTime: '', guessed: false })
    // "tonight" is the one date word that also names an hour. 19:00 is a
    // convention, not a reading, so it is always flagged as a guess.
    expect(parse('pick up milk tonight')).toEqual({ summary: 'pick up milk', dueDate: '2026-08-21', dueTime: '19:00', guessed: true })
  })

  it('lets an explicit time win over tonight’s 19:00', () => {
    // "tonight" only supplies the hour when the line supplied none.
    expect(parse('drinks tonight at 9pm')).toEqual({ summary: 'drinks', dueDate: '2026-08-21', dueTime: '21:00', guessed: false })
  })

  it('reads a bare weekday as the NEXT one, strictly after today', () => {
    // NOW is a Friday, which is the ambiguous case and the reason the rule is
    // "strictly after": someone typing "friday" on a Friday morning has a word
    // for the day they are standing in, and it is "today".
    expect(parse('gym friday').dueDate).toBe('2026-08-28')
    expect(parse('gym saturday').dueDate).toBe('2026-08-22')
    expect(parse('call on wednesday').dueDate).toBe('2026-08-26')
  })

  it('reads "next <weekday>" as a week past that', () => {
    // The genuine ambiguity in the whole grammar: on a Friday, "next monday" is
    // read by some people as the coming Monday and by others as the one after.
    // Ruled the way the contract states — next = the bare reading plus seven —
    // so that "friday"/"next friday" are always a week apart, which is at least
    // a rule a user can learn from one use.
    expect(parse('gym next friday').dueDate).toBe('2026-09-04')
    expect(parse('gym next monday').dueDate).toBe('2026-08-31')
    expect(parse('launch next thu').dueDate).toBe('2026-09-03')
  })

  it('reads "this <weekday>" as the plain next one', () => {
    // "this" only introduces; it does not shift. On a Friday, "this friday" and
    // "friday" have to agree or the pair is a trap.
    expect(parse('gym this friday').dueDate).toBe(parse('gym friday').dueDate)
  })

  it('takes full and three-letter forms, in any case', () => {
    expect(parse('gym sat').dueDate).toBe('2026-08-22')
    expect(parse('gym tue').dueDate).toBe('2026-08-25')
    expect(parse('Gym Friday')).toEqual({ summary: 'Gym', dueDate: '2026-08-28', dueTime: '', guessed: false })
    // Four letters is not one of the two forms the grammar admits, and
    // stretching to "tues"/"thurs" would start a list with no natural end.
    expect(parse('gym tues')).toEqual(untouched('gym tues'))
  })

  it('refuses a modifier on a day word that cannot take one', () => {
    // "next tomorrow" names nothing. Leaving both words in the title is the
    // honest outcome; picking a day is not.
    expect(parse('gym next tomorrow')).toEqual(untouched('gym next tomorrow'))
  })

  it('refuses a plural, which is a recurrence in disguise', () => {
    expect(parse('mondays are busy')).toEqual(untouched('mondays are busy'))
  })

  it('refuses a possessive rather than leaving its tail behind', () => {
    // Without the apostrophe guard this reads as tomorrow and hands back
    // "gym on 's route".
    expect(parse('gym on tomorrow’s route')).toEqual(untouched('gym on tomorrow’s route'))
    expect(parse("gym on tomorrow's route")).toEqual(untouched("gym on tomorrow's route"))
  })
})

describe('where a phrase may sit', () => {
  it('takes a phrase at the end of the line', () => {
    expect(parse('standup 3pm').dueTime).toBe('15:00')
    expect(parse('gym friday').dueDate).toBe('2026-08-28')
  })

  it('refuses the same phrase in front of the title', () => {
    // "3pm standup" is a heading, not a sentence, and reading it would leave
    // the entry called "standup" with no way to tell that anything was eaten.
    expect(parse('3pm standup')).toEqual(untouched('3pm standup'))
    expect(parse('9:30 standup')).toEqual(untouched('9:30 standup'))
    expect(parse('friday gym')).toEqual(untouched('friday gym'))
  })

  it('takes a phrase anywhere once at/@/on/by/next/this introduces it', () => {
    expect(parse('on friday gym')).toEqual({ summary: 'gym', dueDate: '2026-08-28', dueTime: '', guessed: false })
    expect(parse('file taxes by friday').dueDate).toBe('2026-08-28')
    expect(parse('lunch with sam at 12:30').dueTime).toBe('12:30')
    // The introducer comes out with the phrase; leaving "on" or "at" stranded
    // in the title would be its own small mangling.
    expect(parse('on next friday gym').summary).toBe('gym')
  })

  it('leaves an earlier bare number alone — rule 1, not the rightmost rule', () => {
    // Reads like rule 7 and is not: rule 1 throws the bare 3 out before there
    // are two candidates to compare, so flipping the preference to leftmost
    // leaves this line byte-identical. The line that does pin rule 7 is
    // "gym at 7 at 8", below.
    expect(parse('Room 3 booking at 4')).toEqual({ summary: 'Room 3 booking', dueDate: '', dueTime: '16:00', guessed: true })
  })

  it('re-reads the line after lifting a phrase out of it', () => {
    // "friday" is neither at the end of the line nor introduced while "at 7" is
    // still sitting behind it. Taking the rightmost phrase first and measuring
    // the next one against what REMAINS is what makes the most natural phrasing
    // in the whole grammar work.
    expect(parse('gym friday at 7')).toEqual({ summary: 'gym', dueDate: '2026-08-28', dueTime: '07:00', guessed: true })
    expect(parse('dentist tomorrow at 10')).toEqual({ summary: 'dentist', dueDate: '2026-08-22', dueTime: '10:00', guessed: true })
    // Either order of the two phrases reads the same.
    expect(parse('dentist at 10 tomorrow')).toEqual(parse('dentist tomorrow at 10'))
  })

  it('ignores whitespace at the ends of the line', () => {
    // A typed line usually still carries the space left before Enter, and the
    // position rule must not turn on it.
    expect(parse('  gym at 7  ')).toEqual({ summary: 'gym', dueDate: '', dueTime: '07:00', guessed: true })
    expect(parse('gym friday ').dueDate).toBe('2026-08-28')
  })
})

describe('at most one date and one time', () => {
  it('keeps the rightmost time and leaves the other where it is', () => {
    // The one line in the suite that pins rule 7 for times: two introduced
    // hours, both legal, so nothing but the preference decides. Flipped to
    // leftmost it reads 07:00 and hands back "gym at 8".
    expect(parse('gym at 7 at 8')).toEqual({ summary: 'gym at 7', dueDate: '', dueTime: '08:00', guessed: true })
  })

  it('keeps the rightmost date and leaves the other where it is', () => {
    // Two dates in one line is a typo or a change of mind; the later word is
    // the one being typed, and the earlier one stays visible in the title so
    // the contradiction is not hidden.
    //
    // The introducer is what makes this the pinning line: with "on" in front of
    // it "friday" is a live candidate too, so only the preference decides —
    // flipped to leftmost this reads 2026-08-28 and hands back "gym tomorrow".
    expect(parse('gym on friday tomorrow')).toEqual({ summary: 'gym on friday', dueDate: '2026-08-22', dueTime: '', guessed: false })
    // Without it, only one candidate ever survives: bare "friday" is neither
    // trailing nor introduced, so the position rule has it and the preference
    // never comes into the answer.
    expect(parse('gym friday tomorrow')).toEqual({ summary: 'gym friday', dueDate: '2026-08-22', dueTime: '', guessed: false })
  })
})

describe('the empty-residue guard', () => {
  // Rule 4. Each of these is nothing BUT a date or a time, so reading it would
  // leave an entry with no title at all — which is worse than an entry with no
  // date, because the title is the only part that says what to do.
  it.each(['tonight', 'tomorrow', 'today', '3pm', 'friday', 'at 7', '14:00'])(
    'hands back %j untouched rather than emptying the title', (text) => {
      expect(parse(text)).toEqual(untouched(text))
    })

  it('abandons the whole parse, not just the phrase that emptied it', () => {
    // "3pm tomorrow" has already had its date read by the time the time phrase
    // empties the title. Keeping that date would author an untitled entry for
    // tomorrow; the contract says to drop everything and hand the line back.
    expect(parse('3pm tomorrow')).toEqual(untouched('3pm tomorrow'))
    expect(parse('tonight at 9')).toEqual(untouched('tonight at 9'))
  })

  it('still reads a line that keeps one word', () => {
    expect(parse('gym 3pm tomorrow')).toEqual({ summary: 'gym', dueDate: '2026-08-22', dueTime: '15:00', guessed: false })
  })
})

describe('the empty line', () => {
  it('hands an empty or whitespace-only line straight back', () => {
    // Where the summary contract stops. Rule 4 refuses to eat a line's last
    // word, but nothing in the module invents a title, so a line with no word
    // in it comes back exactly as it went in — '' in, '' out, and the spaces of
    // a line that is only spaces kept as typed.
    expect(parse('')).toEqual(untouched(''))
    expect(parse('   ')).toEqual(untouched('   '))
    expect(parse('\t')).toEqual(untouched('\t'))
  })
})

describe('anti-false-positives', () => {
  // The corpus. Every row must come back byte-for-byte, because every row is a
  // legitimate title that a looser reading would eat a piece of. The note names
  // the rule that actually refuses the row, taken from instrumenting the
  // scanner rather than from reading the guards: most of these lines die at
  // rule 1, with the character guards standing behind it and never asked.
  it.each([
    ['Pay invoice 1099', 'rule 1: a bare integer is never a clock, and 10/99 are pieces of a longer number'],
    ['$300 deposit', 'rule 1 again — the currency guard stands behind it and is never reached for this line'],
    ['3km run', 'rule 1 has the bare 3; the letter after it is the guard behind that'],
    ['run 3km', 'the same with the number last — the "km" keeps it off the end of the line too'],
    ['20% raise', 'rule 1; the percent guard bites only on an introduced line, as "raise at 20%" below shows'],
    ['invoice due 3/4', 'a numeric date: no stored format preference exists to read it with, and rule 1 refuses both halves'],
    ['read pages 10-20', 'a range, and rule 1 has both ends of it — the unintroduced spelling needs no range guard'],
    ['release v2:1', 'a one-digit minute is not a minute, so no clock forms and two bare integers are left'],
    ['release v2:10', 'a letter immediately before the hour'],
    ['stamp 10:30:45', 'a legal time form refused by the position rule: the ":45" keeps "10:30" off the end of the line'],
    ['move to 3.30', 'rule 1 on both numbers; the dot guard is what refuses the introduced "meet at 3.30" below'],
    ['meet at 3.30', 'introduced, so the dot is the only thing refusing it, and "meet .30" at 15:00 is what it saves'],
    ['meet at 5th street', 'an ordinal, and the worst mangling available: "meet th street"'],
    ['gym at 730', 'three digits, not four: the guard is the "0" sitting straight after the "73"'],
    ['gym at 1930', 'four digits, and the case the digit guard is load-bearing for — "73" is no hour to begin with, "19" is'],
    ['call at 7 p.m.', 'a meridiem the grammar does not spell would otherwise be read as 07:00'],
    ['buy 2 tickets', 'a quantity, unintroduced and mid-line'],
    ['call 555 1234', 'a phone number is two bare integers'],
    ['Q3 planning', 'rule 1 has the bare 3; the letter before it is the guard behind that'],
    ['order 12 units', 'a quantity, unintroduced'],
    ['run for 30 min', 'a duration: a VTODO has no duration to put it in'],
    ['standup 14:00-15:00', 'a range glued with a hyphen: the second half ends the line and dies on the character before it'],
    ['call back in 2 hours', 'relative to now, which this module refuses to read'],
  ])('leaves %j alone — %s', (text) => {
    expect(parse(text)).toEqual(untouched(text))
  })

  // The two character classes, one line per character. These read oddly on
  // purpose: only a candidate that marks ITSELF as a clock ever reaches the
  // before-guard — a bare number is gone at rule 1, and an introducer puts its
  // own space or "@" in front of the digits — so pinning the character before
  // takes a colon or a meridiem behind it. Each line reads a time and loses the
  // rest of its title if its character leaves the class, which is what the
  // comment beside it names.
  it.each([
    ['row #12:30', 'a hash: "row #" at 12:30'],
    ['fee $5pm', 'a dollar sign: "fee $" at 17:00'],
    ['fare €5:30', 'a currency sign the literal class does not spell: "fare €" at 17:30'],
    ['off 20%3pm', 'a percent sign: "off 20%" at 15:00'],
    ['meet 2/3pm', 'a slash, which is how a pair of alternatives is typed: "meet 2/" at 15:00'],
    ['meet 3.05pm', 'a dot: "meet 3." at 17:00, an hour the line never mentions'],
  ])('refuses %j on the character before the clock — %s', (text) => {
    expect(parse(text)).toEqual(untouched(text))
  })

  // And the two on the after side that no other guard covers, both on
  // introduced lines, where neither rule 1 nor the position rule can help.
  it.each([
    ['raise at 20%', 'a percent sign: "raise %" at 20:00'],
    ['due at 3/4', 'a slash: "due /4" at 15:00'],
  ])('refuses %j on the character after the clock — %s', (text) => {
    expect(parse(text)).toEqual(untouched(text))
  })

  it('never hands back an empty title for a line with words in it', () => {
    // The property behind rule 4, stated over the whole corpus above plus the
    // lines that DO parse.
    for (const text of [
      'gym at 7', 'standup 3pm', 'gym friday at 7', 'Pay invoice 1099', 'tonight',
      'Room 3 booking at 4', '3pm tomorrow', '  gym at 7  ',
    ]) expect(parse(text).summary.trim()).not.toBe('')
  })
})

describe('ranges and lists, which have nowhere to live on a VTODO', () => {
  // A VTODO has a DUE and no end and no duration, so neither half of a range is
  // the answer and the module refuses the whole phrase. Every weekday row below
  // used to come back as ONE of its days with the separator left dangling —
  // "gym mon-fri" as "gym mon-" due 2026-08-28 — which is precisely the silent
  // title loss the module header says the module exists to prevent.
  it.each([
    'gym mon-fri', 'shift sat-sun', 'office mon–fri', 'gym mon—fri', 'gym mon - fri',
    'meet sat/sun', 'standup mon,wed,fri', 'class tue&thu', 'gym mon to fri',
    'gym sat and sun', 'gym monday through friday',
    // With an introducer both halves are live candidates, so both have to be
    // refused: the introduced first day is as wrong an answer as the trailing
    // last one.
    'gym on mon-fri', 'gym on mon to fri',
  ])('refuses the weekday range %j whole', (text) => {
    expect(parse(text)).toEqual(untouched(text))
  })

  // The same for a clock range, which used to be read as its SECOND half:
  // "lunch 12:00 - 13:00" came back as "lunch 12:00 -" due at 13:00. The glued
  // ASCII spelling was already refused; these are the spaced ones and the ones
  // typed with a real dash.
  it.each([
    'lunch 12:00 - 13:00', 'tea at 4:00 - 5:00', 'sync 09:00–10:00', 'call 3pm–4pm',
    'meeting at 7 - 8', 'lunch at 12:00 - 13:00', 'call at 3 - 4 pm', 'gym 7—8',
  ])('refuses the time range %j whole', (text) => {
    expect(parse(text)).toEqual(untouched(text))
  })

  it('still reads a time on a line whose day range it refused', () => {
    // The same trade as the recurrence veto: the range stays in the title where
    // the user can act on it, and an hour takes nothing away from it.
    expect(parse('gym mon–fri at 7')).toEqual({ summary: 'gym mon–fri', dueDate: '', dueTime: '07:00', guessed: true })
  })

  it('still reads a dash used as ordinary punctuation', () => {
    // A digit on the far side of the separator is what makes it a range, and
    // there is none on either side here — "standup" and "urgent" are not
    // numbers — so the clock is read and the dash stays in the title, where it
    // does no harm. Drop that requirement and both of these lines are refused.
    expect(parse('standup - 9:30')).toEqual({ summary: 'standup -', dueDate: '', dueTime: '09:30', guessed: true })
    expect(parse('call mum - 3pm')).toEqual({ summary: 'call mum -', dueDate: '', dueTime: '15:00', guessed: false })
    expect(parse('call bob at 3 - urgent')).toEqual({ summary: 'call bob - urgent', dueDate: '', dueTime: '15:00', guessed: true })
  })
})

describe('the deliberate exclusions', () => {
  it('refuses a date carrying a recurrence marker', () => {
    // VTODO recurrence is gated in this repo (docs/recurrence-findings.md), so
    // "every monday" can only ever be authored as ONE Monday — dropping the
    // repeat, and eating the weekday on the way out to leave "gym every".
    expect(parse('gym every monday')).toEqual(untouched('gym every monday'))
    expect(parse('yoga each tuesday')).toEqual(untouched('yoga each tuesday'))
    // The veto reads the whole left-hand side, not just the word before, so an
    // interval between the marker and the day does not slip past it. Both of
    // these reach it: the day is at the end of the line, so the position rule
    // has already admitted the phrase and the veto is what refuses it.
    expect(parse('run every other friday')).toEqual(untouched('run every other friday'))
    expect(parse('standup every 2nd monday')).toEqual(untouched('standup every 2nd monday'))
    // Refused too, but NOT by the veto: "friday" sits mid-line with nothing
    // introducing it, so the position rule has it first and deleting RECUR
    // entirely would leave this line unchanged. Here as a corpus row, not as
    // evidence for the veto.
    expect(parse('every other friday run')).toEqual(untouched('every other friday run'))
  })

  it('still reads a time on a recurring line, and keeps the repeat visible', () => {
    // Ruled deliberately: the veto exists because eating the WEEKDAY mangles the
    // title. An hour takes nothing away from "every monday", which stays in the
    // title where the user can act on it, so the hour is read as normal.
    expect(parse('gym every monday at 7')).toEqual({ summary: 'gym every monday', dueDate: '', dueTime: '07:00', guessed: true })
    expect(parse('standup daily at 9')).toEqual({ summary: 'standup daily', dueDate: '', dueTime: '09:00', guessed: true })
  })

  it('reads no recurrence out of the bare words', () => {
    for (const text of ['water plants weekly', 'daily journal', 'rent monthly'])
      expect(parse(text)).toEqual(untouched(text))
  })

  it('leaves a timezone standing in the title, and reads the clock as written', () => {
    // Everything this app authors is floating local wall time, so there is
    // nowhere for "PT" to go. It stays in the title rather than being quietly
    // swallowed as though it had been honoured, and it does not shift the hour.
    expect(parse('call vendor at 3pm PT')).toEqual({ summary: 'call vendor PT', dueDate: '', dueTime: '15:00', guessed: false })
  })

  it('refuses the whole line when the zone token displaces the clock from the end', () => {
    // The twin of the case above, and the reason the module comment describes
    // BOTH: with no "at" to introduce it, "3pm" is neither trailing nor
    // introduced, so the position rule refuses the phrase outright and the line
    // survives verbatim. Left unpinned, the comment would be the only record
    // that these two inputs behave differently, and comments drift.
    expect(parse('flight 3pm PT')).toEqual({ summary: 'flight 3pm PT', dueDate: '', dueTime: '', guessed: false })
  })

  it('reads nothing out of a vague horizon', () => {
    for (const text of ['plan next week', 'ship soon', 'reply eod', 'review later'])
      expect(parse(text)).toEqual(untouched(text))
  })
})

describe('dates the backend will accept', () => {
  it('emits only round-trippable YYYY-MM-DD', () => {
    // Rule 6 over the dates the grammar actually produces. What this does NOT
    // pin: every date here is a whole number of days off today's midnight, at
    // most a fortnight out, so `dayOut`'s guard passes on all of them and
    // replacing it with a passthrough leaves this test green. It is a property
    // check, not a guard test — the guard is pinned below.
    for (const text of [
      'gym today', 'gym tomorrow', 'gym friday', 'gym next friday', 'gym sun',
      'gym next wed', 'gym this sat', 'drinks tonight',
    ]) {
      const { dueDate } = parse(text)
      expect(dueDate).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      expect(ymd(parseDate(dueDate))).toBe(dueDate)
    }
  })

  it('refuses a day it cannot write as YYYY-MM-DD', () => {
    // `dayOut`'s guard, reached the one way the public surface can reach it:
    // `now` is a parameter, and `ymd` renders a year outside 1000-9999 with the
    // wrong number of digits — "999-01-02" is not a date `parseDate` or the
    // backend would read as one. No date is emitted, so the line comes back
    // whole rather than carrying a value the rest of the app would resolve to
    // some other day.
    expect(parse('gym tomorrow', new Date(999, 0, 1))).toEqual(untouched('gym tomorrow'))
    expect(parse('gym friday', new Date(999, 0, 1))).toEqual(untouched('gym friday'))
    // An unreadable clock is refused the same way rather than emitting "NaN".
    expect(parse('gym tomorrow', new Date(NaN))).toEqual(untouched('gym tomorrow'))
    // The guard's other half — rendering with `ymd` and reading back with
    // `parseDate` — has no input that reaches it: `ymd` and `parseDate` are
    // exact inverses for every four-digit year, so nothing that passes the
    // pattern test can fail the round trip. It stays as defence for a later
    // edit that emits a date some way other than `addDays`.
  })

  it('rolls over a year end', () => {
    // 2026-12-31 is a Thursday, so the next Friday is in the following year —
    // the case where month and year arithmetic done by hand goes wrong.
    const nye = new Date(2026, 11, 31, 10, 0)
    expect(parse('gym friday', nye).dueDate).toBe('2027-01-01')
    expect(parse('gym next friday', nye).dueDate).toBe('2027-01-08')
    expect(parse('gym tomorrow', nye).dueDate).toBe('2027-01-01')
  })
})

describe('daylight saving', () => {
  it('walks to tomorrow by calendar day, not by 86 400 000 milliseconds', () => {
    // 2026-11-01 is the Sunday the clocks go back in America/New_York, the zone
    // vite.config pins the suite to. That local day is 25 hours long, so adding
    // a day's worth of milliseconds to its midnight lands at 23:00 on the SAME
    // day and "tomorrow" comes back as today. `addDays` moves the date field
    // instead, so it crosses intact.
    const fallBack = new Date(2026, 10, 1, 10, 0)
    expect(parse('gym tomorrow', fallBack).dueDate).toBe('2026-11-02')
    // And the trap really is live in this zone, rather than hypothetical.
    const midnight = new Date(2026, 10, 1)
    expect(ymd(new Date(midnight.getTime() + 86_400_000))).toBe('2026-11-01')
  })

  it('counts weekdays across a spring-forward too', () => {
    // 2026-03-08 is the 23-hour day. Counting from Friday the 6th to Monday the
    // 9th steps over it.
    const beforeSpring = new Date(2026, 2, 6, 10, 0)
    expect(parse('gym monday', beforeSpring).dueDate).toBe('2026-03-09')
    expect(parse('gym next monday', beforeSpring).dueDate).toBe('2026-03-16')
  })
})

describe('known costs, pinned so that changing them is a decision', () => {
  it('takes an introduced bare hour mid-line, street number and all', () => {
    // The position rule admits an introduced phrase anywhere, and "at" is the
    // only marker the grammar gives a bare hour, so this reads 10:00 and the
    // street number leaves the title. Requiring end-of-line for a bare hour
    // would fix it and would also refuse "call mum at 6 about the car", which
    // the rule admits on purpose. Recorded here so the trade is visible.
    expect(parse('meet at 10 downing st')).toEqual({ summary: 'meet downing st', dueDate: '', dueTime: '10:00', guessed: true })
  })

  it('refuses a day beside a separator, whether it is a range or a sentence', () => {
    // "to" and "and" join the two halves of a range and also join the two
    // halves of a sentence, and nothing at this altitude can tell which — so
    // "call bob on friday to confirm", which used to read 2026-08-28 and hand
    // back "call bob to confirm", is refused along with "gym on mon to fri",
    // which used to read the same Friday and hand back "gym on mon to". A miss,
    // which the module's bargain allows and which leaves the whole line
    // standing; reading a range as one of its days is the mangling it does not
    // allow. The comma costs the same way: "pick up milk, tomorrow" used to
    // read 2026-08-22 and leave the comma dangling.
    expect(parse('call bob on friday to confirm')).toEqual(untouched('call bob on friday to confirm'))
    expect(parse('pick up milk, tomorrow')).toEqual(untouched('pick up milk, tomorrow'))
  })

  it('reads the three-letter weekday forms even when they are ordinary words', () => {
    // "sun", "sat", "wed" and "mon" are all English words. The grammar asks for
    // the short forms because "gym sat" is exactly what people type, and the
    // price is this.
    expect(parse('enjoy the sun')).toEqual({ summary: 'enjoy the', dueDate: '2026-08-23', dueTime: '', guessed: false })
  })
})
