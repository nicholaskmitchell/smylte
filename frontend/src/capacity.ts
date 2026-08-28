// How long the owner says they will work, and the two ways they are allowed to
// say it.
//
// Sunsama's planning ritual opens by asking when you want to STOP — "I finish at
// six" — and that is a far more natural sentence than "I will work 312 minutes".
// But a stop time is not a stable quantity: said at 09:00 it means eight hours,
// said at 14:00 it means three, and which of them it means depends on WHICH
// CLOCK IS ASKED. There are already three ideas of "now" in this app (the
// browser's, `home_timezone`, and the server's, which is UTC in the ordinary
// deployment), and a capacity that had to be re-derived on every read would
// inherit all of them — a day whose budget changed depending on which tab you
// looked at it in.
//
// So: BOTH SPELLINGS IN, MINUTES OUT, resolved once at the moment of typing.
// `parseCapacity` takes a clock as a parameter for exactly the reason
// `daytext.parseEntry` does — so the reading of a line is decidable, and
// testable, without the wall clock — and what gets stored is a plain number that
// no later reader has to interpret.
//
// React-free like time.ts, tabs.ts and daytext.ts, with its tests beside it.

import { HABIT_DAYS } from './api'
import { fmtDuration } from './time'

/** The most minutes a capacity may be: a day. Matches the server's bound
 *  (`app.py`'s `day_capacity_minutes`), which exists because an unbounded int
 *  reaches SQLite as an OverflowError — outside the taxonomy the routes map,
 *  and so a 500 rather than a 422. */
export const MAX_CAPACITY = 1440

// ── one grammar, two languages ─────────────────────────────────────────────
//
// `daytext.ts` needed a grammar per language and this file does not, and the
// difference is worth stating rather than looking like an oversight. That module
// DELETES the phrase it recognised from a title somebody typed, so a word read
// in the wrong language costs a word; this one reads a whole field whose only
// content is the quantity, and a line it cannot read leaves the field alone.
// There is nothing here to mangle.
//
// So the German spellings are added to the same patterns rather than switched
// between: `bis` beside `until`, `Uhr` beside the meridiem, `Std.` beside `h`
// and `Min.` beside `m`. None of them collides with an English one — nobody
// types "bis" in this field meaning anything else — and a field that takes both
// is a field that keeps working when an account switches language mid-week.

/** `5h`, `5h30`, `5h 30m`, `90m`, `1.5h`, `5 Std. 30 Min.`, or a bare number of
 *  minutes.
 *
 *  The minute UNIT is optional so that `5h30` reads — it is how a span gets
 *  typed at least as often as `5h 30m`. That would also let a bare number match
 *  the minute group, which is exactly right and exactly why the bare-integer
 *  branch runs first: it claims that case explicitly rather than leaving it to
 *  fall through a grammar whose groups are all optional.
 *
 *  `std` and `stunden?` come before the bare `h` in the hour alternation, and
 *  `min` before the bare `m`, because a regex alternation is first-match: with
 *  `h` first, "5 std" would match the hour as `h` and leave "td" unconsumed. */
const SPAN_RE = /^(?:(\d+(?:\.\d+)?)\s*(?:std\.?|stunden?|h(?:ours?)?))?\s*(?:(\d+)\s*(?:min\.?|minuten?|m(?:ins?|inutes?)?)?)?$/i

/** `until 6pm`, `till 18:00`, `to 5.30pm`, `bis 18 Uhr`, or a bare `6pm`. The
 *  introducer is optional because "6pm" alone is unambiguous — there is no span
 *  it could be confused with, since a span always carries its unit.
 *
 *  German's `Uhr` is a trailing MARKER rather than a meridiem — it says the
 *  number is a clock and nothing about which half of the day — so it is captured
 *  apart from `am|pm` and never reaches `stopTimeToMinutes`' meridiem branch. */
const STOP_RE = /^(?:un?til|till|til|to|bis)?\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\s*(uhr)?$/i

/**
 * Read a typed capacity into minutes, or null when the line says nothing usable.
 *
 * `now` is the clock a STOP TIME is measured from, and is a parameter rather
 * than `new Date()` so the reading is decidable — the same bargain `daytext.ts`
 * strikes. It is unused for a span, which is the point: "5h" means five hours
 * whenever it is typed, and only "until 6pm" needs to know when now is.
 *
 * `opts.stopTime: false` refuses a stop time outright, for the caller that
 * stores a SETTING rather than a statement about today. See the note in the
 * function body.
 *
 * REFUSES rather than guesses, everywhere it is unsure. A line this cannot read
 * leaves the field alone and the owner types something else; a line it reads
 * WRONGLY silently books them a day of the wrong length. So a bare number is
 * minutes (the unit the wire speaks, and the one a "300" in a settings field
 * most likely means), a stop time already past today answers null rather than
 * assuming tomorrow, and anything else is null.
 */
export function parseCapacity(
  input: string, now: Date, opts: { stopTime?: boolean } = {},
): number | null {
  // `stopTime` defaults to true — the day's own control, which is where this
  // grammar was written for, takes "until 6pm" and should go on taking it.
  //
  // It is a parameter because a SETTING must not. CapacitySection's own header
  // says so: "A stop time is deliberately NOT accepted here: 'until 6pm' is a
  // statement about today, and a default that meant 'six hours' on Monday and
  // 'two' on Friday afternoon would be a setting whose value depended on when
  // you last opened Settings." That is exactly what happened — the field called
  // the shared parser, which has this branch, so typing the sentence the app
  // teaches everywhere else stored 90 minutes at 16:30 and 540 at 09:00, as the
  // account-wide default for every day of the week. The comment at the call site
  // asserted "`parseCapacity` ignores the clock for one", which is true of a
  // span and was never true of the input the field actually accepted.
  const allowStop = opts.stopTime !== false
  const raw = input.trim().toLowerCase()
  if (!raw) return null

  // A bare integer is MINUTES. Checked before the span grammar so "300" is not
  // read as three hundred hours by a regex whose unit groups are optional.
  if (/^\d+$/.test(raw)) return clamp(Number(raw))

  const stop = STOP_RE.exec(raw)
  // Guarded on the introducer OR a meridiem OR a colon: without one of those,
  // `STOP_RE` matches a bare number, which the branch above has already claimed.
  const looksLikeStop = !!stop
    && (/^(un?til|till|til|to|bis)/.test(raw) || !!stop[3] || !!stop[4] || /[:.]/.test(raw))
  if (looksLikeStop) {
    // REFUSE rather than fall through to the span grammar. "until 6pm" must not
    // quietly become "6 hours" here — a wrong reading is the one outcome this
    // function's docstring says is worse than no reading.
    if (!allowStop) return null
    const mins = stopTimeToMinutes(stop!, now)
    if (mins !== null) return mins
  }

  const span = SPAN_RE.exec(raw)
  // `[1] || [2]` because the regex's groups are both optional, so it happily
  // matches the empty string and any leftover garbage would otherwise read as
  // zero hours zero minutes — a capacity of nothing, which is a real value and
  // must not be arrived at by accident.
  if (span && (span[1] || span[2])) {
    const hours = span[1] ? Number(span[1]) : 0
    const mins = span[2] ? Number(span[2]) : 0
    return clamp(Math.round(hours * 60 + mins))
  }
  return null
}

/** The minutes from `now` until a parsed stop time today, or null. */
function stopTimeToMinutes(m: RegExpExecArray, now: Date): number | null {
  let hour = Number(m[1])
  const minute = m[2] ? Number(m[2]) : 0
  const meridiem = m[3]
  if (minute > 59) return null
  if (meridiem) {
    if (hour < 1 || hour > 12) return null
    hour = hour % 12 + (meridiem === 'pm' ? 12 : 0)
  } else if (hour > 23) {
    return null
  } else if (hour <= 7) {
    // No meridiem and a small hour: "until 6" almost certainly means the
    // evening, because nobody states a working day that ends before breakfast.
    // This is the one inference in the module and it is bounded — 8 through 23
    // are taken at face value, so only the genuinely ambiguous half of the
    // clock is guessed at.
    hour += 12
  }
  const end = new Date(now)
  end.setHours(hour, minute, 0, 0)
  const mins = Math.round((end.getTime() - now.getTime()) / 60000)
  // A stop time already behind us answers NOTHING rather than tomorrow. "I stop
  // at 6" typed at 7pm is a person correcting a day that has already run over,
  // and silently booking them 23 hours would be the worst possible reading of
  // it. Null leaves the field alone and lets them say what they meant.
  if (mins <= 0) return null
  return clamp(mins)
}

const clamp = (n: number) => Math.max(0, Math.min(MAX_CAPACITY, Math.round(n)))

/**
 * A hand-editable settings blob into a usable per-weekday map.
 *
 * Every settings value is treated as hand-edited here — the same discipline
 * `sanitizeTabOrder`, `isTimeFormat` and `_clean_tokens` apply — and this one
 * FILTERS rather than rejects, so a map written by a newer client that knows a
 * key this build does not still contributes what it can.
 *
 * Keyed by the `HABIT_DAYS` names, never by index, because `service._WEEKDAYS`
 * is documented as the one place those names and Python's weekday numbering
 * meet. A second mapping on this side is exactly how "wed" comes to mean
 * Wednesday on one path and Thursday on the other.
 */
export function sanitizeCapacityByWeekday(v: unknown): Record<string, number> {
  const out: Record<string, number> = {}
  if (!v || typeof v !== 'object' || Array.isArray(v)) return out
  for (const [name, minutes] of Object.entries(v as Record<string, unknown>)) {
    if (!(HABIT_DAYS as readonly string[]).includes(name)) continue
    if (typeof minutes !== 'number' || !Number.isFinite(minutes)) continue
    const n = Math.round(minutes)
    if (n >= 0 && n <= MAX_CAPACITY) out[name] = n
  }
  return out
}

/**
 * What a capacity field should show for `minutes`.
 *
 * `fmtDuration`, so the field speaks the same language as everything else that
 * draws a length of time in this app — and reads back as a person would say it.
 *
 * This used to print a bare number for anything that was not a whole hour, and
 * looking at it caught why that is wrong: typing "until 6pm" at half past four
 * left the field reading `89`. Correct, and useless — the owner said a time and
 * got back an integer with no unit, which reads as a different kind of thing
 * entirely. `1h 29m` is the same fact said back to them.
 *
 * Every shape it produces ROUND-TRIPS through `parseCapacity` — "5h", "1h 29m",
 * "45m", "0m" all read back to the number they came from — which is what lets
 * this be the field's value rather than a label beside it. A test walks that
 * loop rather than trusting it.
 */
export function capacityInput(minutes: number | null): string {
  return minutes == null ? '' : fmtDuration(minutes)
}
