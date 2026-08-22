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

import { addDays, pad, parseDate, ymd } from './util'

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

/** Every time the grammar admits, and a few it does not, which the guards below
 *  then throw out. One regex rather than three because the guards have to see
 *  the candidate's neighbouring characters, and that is far easier to get right
 *  with a single match whose start and end are known.
 *
 *  Groups: 1 `at`, 2 `@`, 3 hour, 4 minute, 5 meridiem. The introducer is part
 *  of the match so the whole phrase — not just the digits — comes out of the
 *  title. `[ \t]` rather than `\s`, so a phrase can never be stitched together
 *  across a line break. */
const TIME_RE = /(?:\b(at)[ \t]+|(@)[ \t]*)?(\d{1,2})(?::(\d{2}))?(?:[ \t]*(am|pm)\b)?/gi

/** The weekday names, full and three-letter, as the grammar asks for. Typed as
 *  possibly-undefined because a string index into a Record is not a promise
 *  that the key is there. */
const WEEKDAY: Readonly<Record<string, number | undefined>> = {
  sunday: 0, sun: 0, monday: 1, mon: 1, tuesday: 2, tue: 2, wednesday: 3,
  wed: 3, thursday: 4, thu: 4, friday: 5, fri: 5, saturday: 6, sat: 6,
}

/** Every date the grammar admits.
 *
 *  Groups: 1 `at|on|by`, 2 `@`, 3 `next|this`, 4 the day word. `next`/`this` sit
 *  in their own optional group AFTER the plain introducers so "on next friday"
 *  is one phrase; otherwise "on" would be stranded in the title when the rest
 *  of the phrase was lifted out.
 *
 *  `\b` on both ends keeps "3friday" and "mondays" out — a plural is a
 *  recurrence in disguise and must not be read as one day. The lookahead adds
 *  the apostrophe that `\b` does not cover, so "gym on tomorrow's route" is not
 *  read as tomorrow with a title of "gym 's route". */
const DATE_RE =
  /(?:\b(at|on|by)[ \t]+|(@)[ \t]*)?(?:\b(next|this)[ \t]+)?\b(today|tonight|tomorrow|sunday|sun|monday|mon|tuesday|tue|wednesday|wed|thursday|thu|friday|fri|saturday|sat)\b(?!['’])/gi

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
 *  every line it catches carries a colon or a meridiem: a bare number is gone
 *  at rule 1 before any guard runs, and an introduced one has the introducer's
 *  space or its `@` in front of the digits rather than any of these characters.
 *  "release v2:10" (a letter), "standup 14:00-15:00" (the hyphen before the
 *  second half), "meet 2/3pm", "meet 3.05pm", "row #12:30", "fee $5pm",
 *  "fare €5:30" and "off 20%3pm" are the shapes that die here — "Pay invoice
 *  1099", "$300 deposit" and "invoice due 3/4" never get this far, because
 *  every candidate in them is a bare integer. */
const BEFORE_BAD = /[#$%\/.\-\d\p{L}\p{Sc}]/u

/** The same, immediately after a candidate.
 *
 *  The rule set names `%/kKmMhs` and a digit; k/K/m/M/h/s are letters, and
 *  generalising to every letter is what saves "meet at 5th street" — which
 *  otherwise reads 17:00 and hands back "meet th street", the single worst
 *  mangling this module can produce. The percent and the slash earn their keep
 *  on introduced lines, where no other guard would refuse them: without them
 *  "raise at 20%" reads 20:00 and hands back "raise %", and "due at 3/4" reads
 *  15:00 and hands back "due /4". The digit is what refuses "gym at 1930". */
const AFTER_BAD = /[%\/\d\p{L}]/u

/** A separator wedged directly between two numbers.
 *
 *  Conditional on the digit, unlike the sets above: a trailing "." with a space
 *  after it is ordinary punctuation, but one glued to another number means the
 *  candidate is part of a larger construct — "3.30" (a British-style time this
 *  grammar does not read), "10:30:45" (a stamp with seconds), "v1.2". Reading
 *  the head of any of those as a clock would leave its tail behind in the
 *  title. "meet at 3.30" is the shape that needs it: introduced, so neither
 *  rule 1 nor the position rule would refuse it, and without the dot it reads
 *  15:00 and hands back "meet .30".
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

/** The same shape with days in it: a weekday range or list, in the spellings
 *  the box actually sees — "mon-fri", "mon–fri", "gym mon - fri", "sat/sun",
 *  "mon,wed,fri", "tue&thu", "mon to fri", "sat and sun", "monday through
 *  friday".
 *
 *  A day word has no digits for the guards above to hang on, so what marks the
 *  range here is the separator itself, on one side of the word or the other.
 *  Every candidate in the phrase is refused rather than one picked: "gym
 *  mon-fri" read as next Friday, handing back the title "gym mon-", is exactly
 *  the silent loss the header says this module exists to prevent, and the first
 *  day of a range is no better an answer than the last.
 *
 *  The word separators cost a real line — "call bob on friday to confirm" is
 *  refused, where it used to read 2026-08-28. That is a MISS, which the
 *  header's bargain allows and which hands the line back verbatim; reading
 *  "gym on mon to fri" as the Friday and handing back the title "gym on mon
 *  to" is a mangling, which it does not. */
const DAY_RANGE_BEFORE = /(?:[-–—/,&][ \t]*|\b(?:to|and|through)[ \t]+)$/i
const DAY_RANGE_AFTER = /^(?:[ \t]*[-–—/,&]|[ \t]+(?:to|and|through)\b)/i

/** A meridiem the grammar does not spell, e.g. "7 p.m.".
 *
 *  Only `am`/`pm` are read. Without this guard the match would stop at the
 *  hour, the dotted meridiem would be left in the title, and "call at 7 p.m."
 *  would be read as 07:00 by the inference table below — the exact half of the
 *  day the user had ruled out. Refusing is a miss; reading it backwards is a
 *  wrong time on a real entry. */
const DOTTED_MERIDIEM = /^[ \t]*[ap]\.[ \t]?m\.?/i

/** Recurrence markers. See the exclusion note in the header: these veto a DATE
 *  phrase, not a time. Eating the weekday out of "gym every monday" is the
 *  mangling; a bare hour left on "gym every monday at 7" harms nothing and the
 *  repeat stays legible in the title, where the user can act on it. */
const RECUR = /\b(every|each)\b/i

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
function readDay(word: string, mod: string, now: Date): string {
  const base = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  if (word === 'today' || word === 'tonight' || word === 'tomorrow') {
    // "next tomorrow" and "this today" are not phrases. Refusing leaves the
    // words in the title, which is the honest outcome for a line nobody can
    // read; guessing which of two days was meant is not.
    if (mod) return ''
    return dayOut(word === 'tomorrow' ? addDays(base, 1) : base)
  }
  const target = WEEKDAY[word]
  if (target === undefined) return ''      // unreachable through DATE_RE; belt for a later edit
  // Strictly after today: a bare "friday" typed ON a Friday means the next one.
  // The day already half spent is the one reading the user cannot have meant,
  // since they would have typed "today".
  const ahead = ((target - base.getDay() + 7) % 7) || 7
  return dayOut(addDays(base, mod === 'next' ? ahead + 7 : ahead))
}

/** Every time phrase in `text` that survives the guards. `eol` is where the
 *  line ends once trailing whitespace is ignored — a typed line usually still
 *  carries the space left before Enter, and the position rule must not turn on
 *  it. */
function timePhrases(text: string, eol: number): Phrase[] {
  const out: Phrase[] = []
  // `lastIndex` is reset by hand because these regexes are module-level and
  // /g-flagged: a previous call that ended early would otherwise start this one
  // partway through the string.
  TIME_RE.lastIndex = 0
  for (let m = TIME_RE.exec(text); m; m = TIME_RE.exec(text)) {
    const [whole, at, sign, hh, mm, mer] = m
    const numAt = m.index + whole.search(/\d/)
    const after = m.index + whole.length
    const introduced = !!(at || sign)
    const rest = text.slice(after)

    // Rule 1: a bare integer is never a time. Only an introducer, a colon or a
    // meridiem makes a number a clock, which is what keeps "Pay invoice 1099",
    // "buy 2 tickets" and "Room 3 booking" whole.
    if (!introduced && !mm && !mer) continue
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

    const clock = readClock(Number(hh), mm ? Number(mm) : 0, mer || '')
    if (!clock) continue
    out.push({ start: m.index, end: after, date: '', time: clock.time, guessed: clock.guessed, tonight: false })
  }
  return out
}

/** Every date phrase in `text` that survives the guards. */
function datePhrases(text: string, eol: number, now: Date): Phrase[] {
  const out: Phrase[] = []
  DATE_RE.lastIndex = 0
  for (let m = DATE_RE.exec(text); m; m = DATE_RE.exec(text)) {
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
    if (DAY_RANGE_BEFORE.test(text.slice(0, wordAt)) || DAY_RANGE_AFTER.test(text.slice(end))) continue
    // The recurrence veto reads everything to the LEFT, not just the word
    // before, so "run every other friday" and "standup every 2nd monday" are
    // refused along with the plain "gym every monday".
    if (RECUR.test(text.slice(0, m.index))) continue

    const key = word.toLowerCase()
    const date = readDay(key, (mod || '').toLowerCase(), now)
    if (!date) continue
    out.push({ start: m.index, end, date, time: '', guessed: false, tonight: key === 'tonight' })
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
function rightmost(text: string, now: Date, wantDate: boolean, wantTime: boolean): Phrase | null {
  const eol = text.trimEnd().length
  const all = [
    ...(wantTime ? timePhrases(text, eol) : []),
    ...(wantDate ? datePhrases(text, eol, now) : []),
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
export function parseEntry(text: string, now: Date): ParsedEntry {
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
    const hit = rightmost(rest, now, !dueDate, !dueTime)
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
