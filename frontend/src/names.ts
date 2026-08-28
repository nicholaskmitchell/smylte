// Weekday and month names, in the app's language.
//
// From `Intl`, and never from the message catalogues. CLDR already knows what
// Wednesday is called in every language the platform ships, in three widths,
// with the abbreviation native readers actually use — "Mi." in German, which is
// not what you get by taking the first three letters of "Mittwoch". Seven
// weekdays and twelve months copied into en.ts and de.ts would be re-keying data
// the browser already has, and the copy is the one that goes stale: it is the
// half of a translation nobody proofreads, because it looks like a constant
// rather than like prose.
//
// The lists these return are ORDERED, and every caller indexes them, so each
// function names the convention it hands back rather than leaving it to be
// guessed. That matters here more than usual: the app has two week orders in
// play at once — the server writes availability and habit days Monday-first,
// while `Date#getDay` counts from Sunday — and an off-by-one between them is a
// bug that shows up on exactly one weekday.

import { HABIT_DAYS } from './api'

/** A real week, Monday first. 2024-01-01 was a Monday.
 *
 *  Noon UTC, not midnight: `toLocaleDateString` renders in the VIEWER's zone,
 *  and a midnight-UTC instant is the previous day for everyone west of
 *  Greenwich — which would silently rotate the whole week by one for half the
 *  planet. Noon is far enough from either edge that no real offset reaches it. */
const MONDAY_WEEK = Array.from({ length: 7 }, (_, i) => new Date(Date.UTC(2024, 0, 1 + i, 12)))

/** One date in each month, for the same reason and with the same guard. The
 *  15th so no month-length or leap-day case is anywhere near it. */
const MONTH_DATES = Array.from({ length: 12 }, (_, i) => new Date(Date.UTC(2024, i, 15, 12)))

export type NameWidth = 'long' | 'short' | 'narrow'

/** Which day the returned week starts on — the CALLER's indexing, not a
 *  regional preference about when a week begins. 'mon' for anything keyed the
 *  way the server writes it, 'sun' for anything keyed by `Date#getDay`. */
export type WeekStart = 'mon' | 'sun'

// Building an `Intl.DateTimeFormat` is not free, and the month grid asks for a
// week of names on every render. The answer depends on nothing but the three
// arguments, so it is cached on them; a couple of dozen entries at the very most
// (three widths, two orders, however many languages one session switches
// between), which is why there is no eviction.
const cache = new Map<string, readonly string[]>()

function memo(key: string, build: () => string[]): readonly string[] {
  const hit = cache.get(key)
  if (hit) return hit
  const built = build()
  cache.set(key, built)
  return built
}

/** The seven weekday names, in `start` order. */
export function weekdayNames(
  locale: string, width: NameWidth = 'long', start: WeekStart = 'mon',
): readonly string[] {
  return memo(`w|${locale}|${width}|${start}`, () => {
    const fmt = new Intl.DateTimeFormat(locale, { weekday: width })
    const mon = MONDAY_WEEK.map((d) => fmt.format(d))
    // Sunday is index 6 of a Monday-first week; moving it to the front is the
    // whole difference between the two conventions.
    return start === 'mon' ? mon : [mon[6], ...mon.slice(0, 6)]
  })
}

/** The twelve month names, indexed the way `Date#getMonth` counts: January is 0. */
export function monthNames(locale: string, width: NameWidth = 'long'): readonly string[] {
  return memo(`m|${locale}|${width}`, () =>
    MONTH_DATES.map((d) => new Intl.DateTimeFormat(locale, { month: width }).format(d)))
}

/**
 * The label for one of `HABIT_DAYS`' tokens — "mon" → "Mon", or "Mo." in German.
 *
 * This used to be `d[0].toUpperCase() + d.slice(1)`, in two components, each
 * carrying a comment explaining that deriving the label from the token was the
 * point: a table mapping these seven names to a weekday NUMBER would be a second
 * copy of a mapping the server already owns, and two copies is how "wed" comes
 * to mean Wednesday on one side and Thursday on the other, for one weekday only.
 *
 * That argument still holds, and this is not the table it warns about. There is
 * no `{ mon: 1, tue: 2 }` here: the index comes from `HABIT_DAYS` itself, whose
 * documented mon..sun order IS the mapping and is the copy that already exists.
 * A token the array does not contain gets the old capitalisation rather than a
 * wrong day — nothing on the wire should produce one, and inventing a weekday
 * for it would be exactly the drift the original comment was guarding against.
 */
export function habitDayLabel(
  token: string, locale: string, width: NameWidth = 'short',
): string {
  const i = HABIT_DAYS.indexOf(token as (typeof HABIT_DAYS)[number])
  if (i < 0) return token ? token[0].toUpperCase() + token.slice(1) : token
  return weekdayNames(locale, width, 'mon')[i]
}
