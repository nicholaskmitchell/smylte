// Reading one typed line in the add-to-my-day box: "gym at 7" becomes an entry
// titled "gym", due at 07:00.
//
// Planning a day has to be cheap or it does not get done, which is why the box
// takes a line of prose instead of a title plus two pickers. The bargain that
// buys is that this module is allowed to MISS — a phrase it does not recognise
// simply stays in the title and the user reaches for the pickers as before.
// What it must never do is recognise something that was not a time, because a
// recognised phrase is DELETED from the title the entry keeps: "Pay invoice
// 1099" coming back as "Pay invoice" is silent loss of the one field carrying
// the meaning, and it is the kind of loss nobody notices until the entry is
// useless. So every rule below refuses first and reads second, and the guards
// take up more of this file than the grammar they defend.
//
// React-free like tabs.ts, order.ts and time.ts, with its tests beside it: the
// reading of a line is decidable on its own, and `now` is a parameter precisely
// so the whole thing can be pinned by a test rather than by the wall clock.
//
// Two things this module refuses to consult, on purpose:
//
//   * the 12/24-hour setting. That lives in time.ts and is a RENDERING choice;
//     what "3pm" means cannot depend on how the answer will later be drawn, or
//     the same line would produce two different entries on two devices.
//   * the current time of day. A rule that reads "3" as this afternoon before
//     lunch and tomorrow afternoon after it cannot be pinned by any test, and
//     would make one line mean two things in one day. `now` is used for the
//     calendar DAY only, never for the hour.
//
// ── deliberately NOT parsed ────────────────────────────────────────────────
//
// Recurrence of any kind ("every monday", "daily", "weekly"). VTODO recurrence
// is GATED in this repo — docs/recurrence-findings.md says task recurrence and
// its completion-advancement semantics "are not implemented and must not be
// until the device-capture investigation below is done and the design
// approved". A parser that read "every monday" could only ever author a single
// dated task, quietly dropping the repeat that was asked for, and it would eat
// the weekday on the way out and leave "gym every" as the title. So `every` or
// `each` anywhere ahead of a date phrase VETOES that phrase (see `RECUR`);
// "daily"/"weekly"/"monthly" match nothing in the grammar to begin with.
//
// Timezones ("3pm PT"). Every date and time the app authors is floating local
// wall time, so there is nowhere for a zone to go. Nothing here looks for a zone
// token, and the two ways that plays out are both acceptable — but they are not
// the same, so neither is claimed as the rule:
//
//   * "flight 3pm PT" parses NOTHING. The time is neither trailing nor
//     introduced, so the position rule refuses it and the line survives
//     verbatim.
//   * "flight at 3pm PT" reads 15:00 and leaves "PT" standing in the title,
//     where whoever typed it can still see that it was not honoured.
//
// The second is the one that matters: a zone is never silently swallowed as if
// it had been applied. The first is simply the position rule doing its job.
//
// Durations and ranges ("for 30 min", "14:00-15:00", "mon-fri"). A VTODO has a
// DUE and no end and no duration, so the second half of a range has nowhere to
// live — and keeping either half alone would author something the user did not
// say. So no half of a range is ever read: whichever one the position rule
// would have admitted, an adjacency guard below refuses it. `RANGE_BEFORE` and
// `RANGE_AFTER` do that for a clock range in any spelling the box sees (glued,
// spaced, hyphen or en/em dash); `DAY_RANGE_BEFORE` and `DAY_RANGE_AFTER` do it
// for the same shape drawn with days — "mon-fri", "sat/sun", "mon,wed,fri",
// "tue&thu", "mon to fri".
//
// Numeric dates ("3/4"). No stored date-format preference exists anywhere in
// this app to disambiguate D/M from M/D, so this is a coin flip between two
// dates three weeks apart. A miss costs a tap; a wrong month is a missed
// deadline.
//
// Vague horizons ("next week", "eod", "soon") and relative-to-now ("in 2
// hours"). None of them names a day without a policy nobody has agreed on, and
// the relative ones would put the wall clock back into the reading.

// ── two languages, two grammars ────────────────────────────────────────────
//
// The rules above are about SHAPES — a bare integer is not a clock, a range has
// nowhere to live, a recognised phrase must never eat the last word — and those
// hold whatever language the line is in. The WORDS do not, so every word this
// module knows sits in `GRAMMARS`, one entry per language, and the scanners take
// the grammar as a parameter. Nothing else is duplicated: both languages run the
// same guards, the same position rule and the same inference table, so a fix to
// any of them fixes both.
//
// The German grammar admits what the English one admits, said in German, and
// then stops. Three deliberate absences, each for the reason the header already
// gives:
//
//   * `übermorgen`. A common enough word, but JavaScript's `\b` is defined by
//     ASCII `\w`, so it does not match before `ü` — the anchor that keeps
//     "3friday" out cannot be written for it, and a day word admitted mid-word
//     is the kind of hole this file exists to not have.
//   * The two-letter abbreviations (Mo, Di, Mi, Do, Fr, Sa, So). `so` is an
//     ordinary German word, so admitting them would import the "enjoy the sun"
//     mangling the English short forms already carry — knowingly, into a second
//     language, where nothing forces it.
//   * The dotted clock ("19.30 Uhr"). It is the standard German spelling and it
//     is still refused: `1.30` is also a version number, a decimal and a price,
//     and the colon form is what the box's own placeholder teaches. "19:30 Uhr"
//     and "um 19:30" both read.
//
// German has no meridiem, so the fifth group of its time pattern is `Uhr`, which
// MARKS a number as a clock the way a colon does without saying which half of
// the day it is — see `Grammar.meridiem`.

import { addDays, pad, parseDate, ymd } from './util'
import { DEFAULT_LANGUAGE, type Language } from './lang'

/** What the box managed to read out of one typed line. */
export interface ParsedEntry {
  /** The title with the recognised phrase removed. Never empty for a line that
   *  had a word in it — rule 4 abandons the whole reading rather than hand back
   *  a titleless entry — but nothing here manufactures a title, so an empty or
   *  whitespace-only line comes back exactly as it went in: '' in, '' out. When
   *  nothing is recognised this is the input verbatim, byte for byte. */
  summary: string
  /** YYYY-MM-DD, or '' when no date phrase was recognised. */
  dueDate: string
  /** HH:MM, 24-hour and zero-padded, or '' when no time phrase was recognised.
   *  A time with no date is normal — "gym at 7" names an hour and leaves the
   *  day to the caller, which is planning a particular day already. */
  dueTime: string
  /** True when the meridiem — or the whole reading, as with "tonight" — was
   *  inferred rather than stated, so the view can mark it as a guess. */
  guessed: boolean
}

// ── grammar ────────────────────────────────────────────────────────────────

/** Everything about reading a line that is a fact about the LANGUAGE it is in.
 *
 *  Everything NOT in here — the position rule, the range and adjacency guards,
 *  the inference table, rule 4's refusal to eat the last word — is a fact about
 *  shapes, and is shared. */
interface Grammar {
  /** Every time the grammar admits, and a few it does not, which the guards
   *  below then throw out. One regex rather than three because the guards have
   *  to see the candidate's neighbouring characters, and that is far easier to
   *  get right with a single match whose start and end are known.
   *
   *  Groups: 1 introducer word, 2 `@`, 3 hour, 4 minute, 5 the clock marker.
   *  The introducer is part of the match so the whole phrase — not just the
   *  digits — comes out of the title. `[ \t]` rather than `\s`, so a phrase can
   *  never be stitched together across a line break. */
  time: RegExp
  /** Whether group 5 of `time` states a HALF OF THE DAY (English's am/pm) or
   *  merely marks the number as a clock (German's "Uhr"). Both satisfy rule 1 —
   *  the number is no longer bare — but only a meridiem overrides the inference
   *  table, which is why they are not the same flag. */
  meridiem: boolean
  /** Every date the grammar admits.
   *
   *  Groups: 1 introducer word, 2 `@`, 3 modifier, 4 the day word. The modifier
   *  sits in its own optional group AFTER the plain introducers so "on next
   *  friday" is one phrase; otherwise "on" would be stranded in the title when
   *  the rest of the phrase was lifted out.
   *
   *  `\b` on both ends keeps "3friday" and "mondays" out — a plural is a
   *  recurrence in disguise and must not be read as one day. The lookahead adds
   *  the apostrophe that `\b` does not cover, so "gym on tomorrow's route" is
   *  not read as tomorrow with a title of "gym 's route". */
  date: RegExp
  /** The day words that are not weekdays, lowercased. `tonight` is the one that
   *  also implies an hour. */
  today: readonly string[]
  tonight: readonly string[]
  tomorrow: readonly string[]
  /** The weekday names the grammar asks for, full and abbreviated, to the day
   *  number `Date#getDay` uses. */
  weekday: Readonly<Record<string, number | undefined>>
  /** A weekday range or list, checked on either side of the day WORD. */
  dayRangeBefore: RegExp
  dayRangeAfter: RegExp
  /** Recurrence markers, vetoing a date phrase anywhere to their right. */
  recur: RegExp
  /** Which of the `date` pattern's modifiers means the week AFTER the next
   *  occurrence, rather than that occurrence itself. Every other modifier the
   *  pattern admits reads as "this one". */
  nextWeek: RegExp
  /** A phrase the pattern matched that the language does not mean. `left` is
   *  everything before the phrase, `intro` and `word` are lower-cased. */
  veto?: (intro: string, word: string, left: string) => boolean
}

const EN_WEEKDAY: Readonly<Record<string, number | undefined>> = {
  sunday: 0, sun: 0, monday: 1, mon: 1, tuesday: 2, tue: 2, wednesday: 3,
  wed: 3, thursday: 4, thu: 4, friday: 5, fri: 5, saturday: 6, sat: 6,
}

// Sonnabend is Sonntag's neighbour in the north and east and means Saturday;
// it costs one alternative and nothing else.
const DE_WEEKDAY: Readonly<Record<string, number | undefined>> = {
  sonntag: 0, montag: 1, dienstag: 2, mittwoch: 3, donnerstag: 4,
  freitag: 5, samstag: 6, sonnabend: 6,
}

const DE_DAYS = 'montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag'

export const GRAMMARS: Readonly<Record<Language, Grammar>> = {
  en: {
    time: /(?:\b(at)[ \t]+|(@)[ \t]*)?(\d{1,2})(?::(\d{2}))?(?:[ \t]*(am|pm)\b)?/gi,
    meridiem: true,
    date: /(?:\b(at|on|by)[ \t]+|(@)[ \t]*)?(?:\b(next|this)[ \t]+)?\b(today|tonight|tomorrow|sunday|sun|monday|mon|tuesday|tue|wednesday|wed|thursday|thu|friday|fri|saturday|sat)\b(?!['’])/gi,
    today: ['today'],
    tonight: ['tonight'],
    tomorrow: ['tomorrow'],
    weekday: EN_WEEKDAY,
    dayRangeBefore: /(?:[-–—/,&][ \t]*|\b(?:to|and|through)[ \t]+)$/i,
    dayRangeAfter: /^(?:[ \t]*[-–—/,&]|[ \t]+(?:to|and|through)\b)/i,
    recur: /\b(every|each)\b/i,
    nextWeek: /^next$/i,
  },
  de: {
    // "um" is the one introducer a bare hour gets, as `at` is in English.
    // "Uhr" is group 5 and is a MARKER, not a meridiem: it says the number is a
    // clock and says nothing about which half of the day, so "7 Uhr" still goes
    // through the inference table and still comes back a guess.
    time: /(?:\b(um)[ \t]+|(@)[ \t]*)?(\d{1,2})(?::(\d{2}))?(?:[ \t]*(uhr)\b)?/gi,
    meridiem: false,
    // `am` and `zum` locate a day, `bis` states a deadline — the three the box
    // actually sees, and the direct analogues of on/at and by. The modifiers
    // carry their inflections because German declines them: nächsten Freitag,
    // nächste Woche, diesen Montag.
    date: /(?:\b(am|bis|zum)[ \t]+|(@)[ \t]*)?(?:\b(nächste[nrms]?|kommende[nrms]?|diese[nrms]?)[ \t]+)?\b(heute abend|heute|morgen|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag)\b(?!['’])/gi,
    today: ['heute'],
    tonight: ['heute abend'],
    tomorrow: ['morgen'],
    weekday: DE_WEEKDAY,
    // The word separators are anchored to a day word, which the English pair
    // deliberately are not — there, "to" and "and" refuse a phrase on their own
    // and "call bob on friday to confirm" is an accepted miss. German cannot
    // afford the same looseness: `bis` is also the deadline introducer, so an
    // unanchored rule would refuse "Rechnung bis Freitag", which is the single
    // most ordinary line this grammar exists to read. Requiring a day on the
    // far side separates "montag bis freitag" from "bis freitag" exactly.
    dayRangeBefore: new RegExp(`(?:[-–—/,&][ \\t]*|\\b(?:${DE_DAYS})[ \\t]+(?:bis|und)[ \\t]+)$`, 'i'),
    dayRangeAfter: new RegExp(`^(?:[ \\t]*[-–—/,&]|[ \\t]+(?:bis|und)[ \\t]+(?:${DE_DAYS})\\b)`, 'i'),
    // "jeden Montag", "alle zwei Wochen". `täglich`/`wöchentlich` match nothing
    // in the grammar to begin with, exactly as `daily`/`weekly` do not.
    recur: /\b(jede[nsrm]?|alle)\b/i,
    // `nächste*` skips a week, exactly as `next` does; `kommende*` and `diese*`
    // name the occurrence already coming, exactly as `this` does. German usage
    // is genuinely split on "nächsten Montag" — plenty of speakers mean the one
    // three days away — and this module cannot ask. Following the English rule
    // is the choice that makes one word mean one thing in both languages, which
    // is worth more here than picking a side in somebody else's argument.
    nextWeek: /^n[äa]chste/i,
    // `morgen` is tomorrow as an adverb and the morning as a noun, and the box
    // is lower-cased prose where the capital that tells them apart cannot be
    // relied on. Three phrases mean the noun and none of them means a day:
    // "am Morgen", "heute Morgen" (which is this morning, already past), and
    // "gestern Morgen". Reading any of them as tomorrow would date an entry a
    // day out and eat the word that said so.
    veto: (intro, word, left) => word === 'morgen'
      && (intro === 'am' || /\b(heute|gestern)[ \t]+$/i.test(left)),
  },
}

/** The hour "tonight" means when the line names no other time. Inferred, so it
 *  is always reported as a guess. */
const TONIGHT_AT = '19:00'

// ── guards ─────────────────────────────────────────────────────────────────

/** Characters that, sitting immediately before a number, mean it is not a clock.
 *
 *  `#$%/.-`, any currency sign and a digit come straight from the rule set.
 *  Letters are here too, generalising the same idea to the other side of the
 *  alphabet — without them "release v2:10" reads as a half-past-two meeting and
 *  the version number leaves the title.
 *
 *  Only a candidate that marks ITSELF as a clock ever reaches this guard, so
 *  every line it catches carries a colon or a clock marker: a bare number is
 *  gone at rule 1 before any guard runs, and an introduced one has the
 *  introducer's space or its `@` in front of the digits rather than any of these
 *  characters. "release v2:10" (a letter), "standup 14:00-15:00" (the hyphen
 *  before the second half), "meet 2/3pm", "meet 3.05pm", "row #12:30", "fee
 *  $5pm", "fare €5:30" and "off 20%3pm" are the shapes that die here — "Pay
 *  invoice 1099", "$300 deposit" and "invoice due 3/4" never get this far,
 *  because every candidate in them is a bare integer. */
const BEFORE_BAD = /[#$%\/.\-\d\p{L}\p{Sc}]/u

/** The same, immediately after a candidate.
 *
 *  The rule set names `%/kKmMhs` and a digit; k/K/m/M/h/s are letters, and
 *  generalising to every letter is what saves "meet at 5th street" — which
 *  otherwise reads 17:00 and hands back "meet th street", the single worst
 *  mangling this module can produce. The percent and the slash earn their keep
 *  on introduced lines, where no other guard would refuse them: without them
 *  "raise at 20%" reads 20:00 and hands back "raise %", and "due at 3/4" reads
 *  15:00 and hands back "due /4". The digit is what refuses "gym at 1930".
 *
 *  It is also what refuses German's dotted clock, by way of `AFTER_PAIR` below:
 *  "19.30 Uhr" dies rather than reading half past seven, and that is the header's
 *  choice rather than an oversight. */
const AFTER_BAD = /[%\/\d\p{L}]/u

/** A separator wedged directly between two numbers.
 *
 *  Conditional on the digit, unlike the sets above: a trailing "." with a space
 *  after it is ordinary punctuation, but one glued to another number means the
 *  candidate is part of a larger construct — "3.30" (a British-style time this
 *  grammar does not read, and the standard German spelling it does not read
 *  either), "10:30:45" (a stamp with seconds), "v1.2". Reading the head of any
 *  of those as a clock would leave its tail behind in the title. "meet at 3.30"
 *  is the shape that needs it: introduced, so neither rule 1 nor the position
 *  rule would refuse it, and without the dot it reads 15:00 and hands back
 *  "meet .30".
 *
 *  After a candidate, every dash spelling is `RANGE_AFTER`'s below, so a range
 *  answers to one guard rather than to two that have to agree. Before one, the
 *  rule set's own hyphen in BEFORE_BAD gets to the glued spelling first —
 *  "standup 14:00-15:00" dies on the character before its second half and never
 *  reaches the range guards at all — and RANGE_BEFORE covers the spaced and
 *  en/em-dash spellings that a single character cannot see. */
const AFTER_PAIR = /^[.:]\d/

/** A range separator between this candidate and a number on the other side of
 *  it: hyphen, en dash or em dash, glued or spaced, before the candidate or
 *  after it.
 *
 *  A range has nowhere to live on a VTODO (see the header), and refusing only
 *  the half the scan happens to reach is no better than reading it — "lunch
 *  12:00 - 13:00" came back as "lunch 12:00 -" due at 13:00, which is the
 *  SECOND half of a range wearing the first half's title. Both sides are
 *  checked because either half can be the one the earlier rules would have
 *  admitted, and which one that is depends on how the range was typed: in
 *  "lunch 12:00 - 13:00" the trailing "13:00" is the live candidate and
 *  RANGE_BEFORE refuses it (the leading "12:00" was never introduced, so the
 *  position rule had it), while in "meeting at 7 - 8" it is the introduced
 *  "at 7" that RANGE_AFTER refuses (the trailing "8" is a bare integer, and
 *  rule 1 had it). Guarding one side only would just move the mangling.
 *
 *  A digit is required on the far side of the separator, which is what keeps a
 *  dash used as ordinary punctuation from refusing the line: "standup - 9:30"
 *  is still 09:30 because "standup" is not a number, and "call bob at 3 -
 *  urgent" is still 15:00 because "urgent" is not one either. The optional
 *  meridiem in RANGE_BEFORE is there because the first half of "call 3pm–4pm"
 *  ends in letters rather than in its digits. */
const RANGE_BEFORE = /\d[ \t]*(?:[ap]m)?[ \t]*[-–—][ \t]*$/i
const RANGE_AFTER = /^[ \t]*[-–—][ \t]*\d/

/** A meridiem no grammar here spells, e.g. "7 p.m.".
 *
 *  Only English's `am`/`pm` are ever read. Without this guard the match would
 *  stop at the hour, the dotted meridiem would be left in the title, and "call
 *  at 7 p.m." would be read as 07:00 by the inference table — the exact half of
 *  the day the user had ruled out. Refusing is a miss; reading it backwards is a
 *  wrong time on a real entry.
 *
 *  Shared rather than per-language, and that is the point rather than an
 *  economy: German has no meridiem of its own, so the guard never fires on a
 *  German line — but "Sport um 7 p.m." is a line somebody types, and the
 *  argument against reading it as 07:00 does not care which language the rest of
 *  the sentence was in. */
const DOTTED_MERIDIEM = /^[ \t]*[ap]\.[ \t]?m\.?/i

/** The shape the backend accepts, and `ymd` cannot pad a year into range. */
const YMD = /^\d{4}-\d{2}-\d{2}$/

// ── reading ────────────────────────────────────────────────────────────────

/** One recognised phrase and where it sat. Exactly one of `date`/`time` is set;
 *  `tonight` marks the one date phrase that also implies an hour. */
interface Phrase {
  start: number
  end: number
  date: string
  time: string
  guessed: boolean
  tonight: boolean
}

/**
 * A Date as YYYY-MM-DD, or '' if the value does not survive a round trip.
 *
 * Every date this module emits goes through here. `parseDate` is the app's own
 * reader of a date-only string, so rendering with `ymd` and reading back with
 * it is the honest check: anything that does not come back identical is a value
 * the rest of the app would resolve to a different day, and the backend would
 * 422 it besides. The pattern test catches the years `ymd` cannot express in
 * four digits — `pad` only ever pads month and day, so year 999 renders
 * "999-01-01" and year 10000 renders "10000-01-01", neither of which is a date.
 */
function dayOut(d: Date): string {
  if (isNaN(d.getTime())) return ''
  const s = ymd(d)
  return YMD.test(s) && ymd(parseDate(s)) === s ? s : ''
}

/**
 * The clock an hour, minute and meridiem name, or null when they name none.
 *
 * The inference table is FIXED: 1-6 read as PM, 7-11 as AM, 12 as noon, and 0
 * and 13-23 as written. It is a table and not a heuristic on purpose — see the
 * header on why neither the display setting nor the current hour is allowed
 * anywhere near it.
 *
 * `guessed` is true exactly when a meridiem was chosen rather than read, which
 * is every 1-12 reading with nothing spelled out. 0 and 13-23 state their own
 * half of the day, so nothing was inferred for them.
 */
function readClock(h: number, m: number, mer: string): { time: string; guessed: boolean } | null {
  if (m < 0 || m > 59) return null                       // rule 2; the regex fixes the width
  if (mer) {
    // An explicit meridiem only makes sense on a 12-hour reading. "13pm" is not
    // a time anybody means, and picking which half they meant is exactly the
    // repair work this module refuses to do.
    if (h < 1 || h > 12) return null
    return { time: `${pad(mer.toLowerCase() === 'pm' ? (h % 12) + 12 : h % 12)}:${pad(m)}`, guessed: false }
  }
  if (h < 0 || h > 23) return null                       // rule 2
  if (h >= 1 && h <= 11) return { time: `${pad(h <= 6 ? h + 12 : h)}:${pad(m)}`, guessed: true }
  if (h === 12) return { time: `12:${pad(m)}`, guessed: true }
  return { time: `${pad(h)}:${pad(m)}`, guessed: false }
}

/**
 * The day a date word names, as YYYY-MM-DD, or '' when it names none.
 *
 * Every answer is a whole number of days from midnight on the day `now` falls
 * on, walked with `addDays`. Never milliseconds: the suite is pinned to
 * America/New_York, where 2026-11-01 is 25 hours long, so midnight plus
 * 86_400_000 lands at 23:00 on 2026-11-01 and "tomorrow" comes back as today.
 * `addDays` moves the date field and leaves the wall clock alone, so it crosses
 * both transitions intact.
 */
function readDay(word: string, mod: string, now: Date, g: Grammar): string {
  const base = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const relative = g.today.includes(word) || g.tonight.includes(word)
    || g.tomorrow.includes(word)
  if (relative) {
    // "next tomorrow" and "this today" are not phrases. Refusing leaves the
    // words in the title, which is the honest outcome for a line nobody can
    // read; guessing which of two days was meant is not.
    if (mod) return ''
    return dayOut(g.tomorrow.includes(word) ? addDays(base, 1) : base)
  }
  const target = g.weekday[word]
  if (target === undefined) return ''      // unreachable through DATE_RE; belt for a later edit
  // Strictly after today: a bare "friday" typed ON a Friday means the next one.
  // The day already half spent is the one reading the user cannot have meant,
  // since they would have typed "today".
  const ahead = ((target - base.getDay() + 7) % 7) || 7
  return dayOut(addDays(base, mod && g.nextWeek.test(mod) ? ahead + 7 : ahead))
}

/** Every time phrase in `text` that survives the guards. `eol` is where the
 *  line ends once trailing whitespace is ignored — a typed line usually still
 *  carries the space left before Enter, and the position rule must not turn on
 *  it. */
function timePhrases(text: string, eol: number, g: Grammar): Phrase[] {
  const out: Phrase[] = []
  // `lastIndex` is reset by hand because these regexes are module-level and
  // /g-flagged: a previous call that ended early would otherwise start this one
  // partway through the string.
  g.time.lastIndex = 0
  for (let m = g.time.exec(text); m; m = g.time.exec(text)) {
    const [whole, at, sign, hh, mm, marker] = m
    // A meridiem STATES a half of the day; a marker only says "this is a
    // clock". Both make a bare number readable — see `Grammar.meridiem`.
    const mer = g.meridiem ? (marker || '') : ''
    const marked = !!marker
    const numAt = m.index + whole.search(/\d/)
    const after = m.index + whole.length
    const introduced = !!(at || sign)
    const rest = text.slice(after)

    // Rule 1: a bare integer is never a time. Only an introducer, a colon or a
    // meridiem makes a number a clock, which is what keeps "Pay invoice 1099",
    // "buy 2 tickets" and "Room 3 booking" whole.
    if (!introduced && !mm && !marked) continue
    // The position rule: at the end of the line, or introduced. A time loose in
    // the middle of a sentence is far more often a quantity than an hour.
    if (!introduced && after !== eol) continue
    // Rule 3, and its two extensions above.
    if (numAt > 0 && BEFORE_BAD.test(text[numAt - 1])) continue
    if (after < text.length && AFTER_BAD.test(text[after])) continue
    if (AFTER_PAIR.test(rest) || DOTTED_MERIDIEM.test(rest)) continue
    // A range, from whichever end the scan entered it. Both sides are read
    // because the position rule admits either half depending on how the line
    // was typed: "lunch 12:00 - 13:00" offers its second half at the end of the
    // line, "lunch at 12:00 - 13:00" its first as an introduced phrase.
    if (RANGE_AFTER.test(rest) || RANGE_BEFORE.test(text.slice(0, m.index))) continue

    const clock = readClock(Number(hh), mm ? Number(mm) : 0, mer)
    if (!clock) continue
    out.push({ start: m.index, end: after, date: '', time: clock.time, guessed: clock.guessed, tonight: false })
  }
  return out
}

/** Every date phrase in `text` that survives the guards. */
function datePhrases(text: string, eol: number, now: Date, g: Grammar): Phrase[] {
  const out: Phrase[] = []
  g.date.lastIndex = 0
  for (let m = g.date.exec(text); m; m = g.date.exec(text)) {
    const [whole, intro, sign, mod, word] = m
    const end = m.index + whole.length
    // `next`/`this` introduce as well as modify, so either alone satisfies the
    // position rule: "next friday gym" is as clearly dated as "gym next friday".
    if (!(intro || sign || mod) && end !== eol) continue
    // A range or a list of days, not one day. Measured against the day WORD's
    // own neighbours rather than the whole match's: the introducer sits on the
    // far side of the word from any separator, so "on mon-fri" is caught on the
    // hyphen after "on mon" and again on the hyphen before "fri".
    const wordAt = end - word.length
    if (g.dayRangeBefore.test(text.slice(0, wordAt))
      || g.dayRangeAfter.test(text.slice(end))) continue
    // The recurrence veto reads everything to the LEFT, not just the word
    // before, so "run every other friday" and "standup every 2nd monday" are
    // refused along with the plain "gym every monday".
    if (g.recur.test(text.slice(0, m.index))) continue

    const key = word.toLowerCase().replace(/[ \t]+/g, ' ')
    // A phrase the pattern matched and the language does not mean — German's
    // "am Morgen" is a time of day, not a date. See `Grammar.veto`.
    if (g.veto?.((intro || '').toLowerCase(), key, text.slice(0, m.index))) continue
    const date = readDay(key, (mod || '').toLowerCase(), now, g)
    if (!date) continue
    out.push({
      start: m.index, end, date, time: '', guessed: false,
      tonight: g.tonight.includes(key),
    })
  }
  return out
}

/** `s` with [start, end) cut out, the seam closed to a single space and both
 *  ends trimmed — the title the entry will actually carry. */
function without(s: string, start: number, end: number): string {
  const head = s.slice(0, start).trimEnd()
  const tail = s.slice(end).trimStart()
  return (head && tail ? `${head} ${tail}` : head || tail).trim()
}

/** The rightmost phrase of a kind still wanted, or null.
 *
 * Rule 7. Not a right-to-left scan: both scanners run left to right and this is
 * a max over the starts of everything they admitted. "gym at 7 at 8" is the
 * line it decides — two introduced hours, both legal, and the later one is the
 * one being typed. "Room 3 booking at 4" is NOT an example of it, however it
 * reads: rule 1 threw the bare 3 out before there was anything to compare. */
function rightmost(
  text: string, now: Date, wantDate: boolean, wantTime: boolean, g: Grammar,
): Phrase | null {
  const eol = text.trimEnd().length
  const all = [
    ...(wantTime ? timePhrases(text, eol, g) : []),
    ...(wantDate ? datePhrases(text, eol, now, g) : []),
  ]
  let best: Phrase | null = null
  for (const p of all) if (!best || p.start > best.start) best = p
  return best
}

/**
 * Read one typed line.
 *
 * `now` is the moment the line was typed, and only its calendar day is ever
 * consulted. Nothing here is a repair: a line this cannot read comes back
 * exactly as it went in.
 *
 * Known costs, so the next reader does not take them for bugs:
 *
 *   * an introduced phrase is admitted anywhere in the line, which the position
 *     rule plainly allows, so "meet at 10 downing st" reads 10:00 and the
 *     street number leaves the title. `at` is the only marker the grammar gives
 *     a bare hour; requiring end-of-line instead would refuse "call mum at 6
 *     about the car", which the rule admits on purpose.
 *   * the three-letter weekday forms the grammar asks for are ordinary English
 *     words, so "enjoy the sun" ends in a weekday and reads as Sunday. Nothing
 *     short of dropping the short forms fixes that, and "gym sat" is the reason
 *     they are there.
 *   * `DAY_RANGE_*` cannot tell a range from a sentence, because "to" and "and"
 *     are both, so "call bob on friday to confirm" is refused where it used to
 *     read Friday. A miss, and the line survives whole; the alternative is
 *     reading "gym on mon to fri" as Monday.
 */
export function parseEntry(
  text: string, now: Date, lang: Language = DEFAULT_LANGUAGE,
): ParsedEntry {
  // Defaulted so every caller and test that predates the Language setting reads
  // exactly the lines it read before. An unknown tag falls back to English
  // rather than to no grammar at all: a settings blob is hand-editable, and a
  // box that suddenly stopped reading anything would be the worse failure.
  const g = GRAMMARS[lang] ?? GRAMMARS[DEFAULT_LANGUAGE]
  // Rule 4's answer, and the answer for a line with nothing in it to read: the
  // input, untouched.
  const verbatim: ParsedEntry = { summary: text, dueDate: '', dueTime: '', guessed: false }

  let rest = text
  let dueDate = ''
  let dueTime = ''
  let guessed = false
  let tonight = false

  // Rule 5: one date phrase and one time phrase, so at most two passes. Each
  // pass re-scans the string with the previous phrase already lifted out, which
  // is what makes "gym friday at 7" work — "friday" is neither at the end of
  // the line nor introduced until "at 7" is gone. Re-scanning rather than
  // remembering offsets also means the second phrase is always measured against
  // the text that will really remain, so two candidates can never overlap.
  for (let pass = 0; pass < 2; pass++) {
    const hit = rightmost(rest, now, !dueDate, !dueTime, g)
    if (!hit) break
    const next = without(rest, hit.start, hit.end)
    // Rule 4: never consume the only word. Abandoning the WHOLE parse rather
    // than this one phrase is deliberate — "3pm tomorrow" has already had its
    // date read by the time the time phrase empties the title, and an entry
    // dated tomorrow with no title at all is worse than an untouched line.
    if (!next) return verbatim
    rest = next
    if (hit.date) {
      dueDate = hit.date
      tonight = hit.tonight
    }
    if (hit.time) dueTime = hit.time
    guessed = guessed || hit.guessed
  }

  if (!dueDate && !dueTime) return verbatim
  // "tonight" carries an hour of its own, but only when the line named no other
  // one: "tonight at 9pm" is 21:00, not 19:00.
  if (tonight && !dueTime) {
    dueTime = TONIGHT_AT
    guessed = true
  }
  return { summary: rest, dueDate, dueTime, guessed }
}
