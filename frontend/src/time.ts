// Clock formatting and duration formatting: the one place that decides 12- or
// 24-hour, and the one place that spells a length of time.
//
// Every time the app renders used to call `toLocaleTimeString` with
// `{ hour: 'numeric', minute: '2-digit' }` and no `hour12`, which means the
// format fell out of the viewer's locale with no way to choose. Seven call
// sites each spelled the same options out again, so there was no single place
// to add the choice to. This is that place.
//
// React-free like tabs.ts, lists.ts and session.ts, so the formatting rules can
// be tested directly rather than through a rendered view.
//
// Each formatter takes an optional `locale` — the BCP-47 tag the app's Language
// setting resolves to (`localeFor` in lang.ts). It is OPTIONAL, and omitting it
// means `undefined`, which is what these calls have always passed: format for
// the device. That keeps every caller that has not been threaded yet, and every
// test written before the setting existed, reading exactly as it did.

import { parseDate } from './util'
import { DEFAULT_LANGUAGE, type Language } from './lang'

export type TimeFormat = '12h' | '24h'

export const TIME_FORMATS: readonly TimeFormat[] = ['12h', '24h']

/** The default when nothing is stored: the format the app has always used. */
export const DEFAULT_TIME_FORMAT: TimeFormat = '12h'

// Settings are a JSON blob a user can hand-edit or import, so the stored value
// is re-validated on the way in rather than trusted.
export function isTimeFormat(v: unknown): v is TimeFormat {
  return v === '12h' || v === '24h'
}

export function nextTimeFormat(f: TimeFormat): TimeFormat {
  return f === '12h' ? '24h' : '12h'
}

/** The catalogue key for this choice, not the text.
 *
 *  A KEY because the label is shown in whatever language the app is set to and
 *  this module is React-free — it has no `t` and should not grow one. Returning
 *  the identity of the label and letting the one component that renders it look
 *  the string up keeps the translation in the catalogue with every other
 *  string, which is the only place a translator has to look. */
export function timeFormatKey(f: TimeFormat): string {
  return f === '24h' ? 'clock.24h' : 'clock.12h'
}

// `hour12` is passed explicitly rather than left to the locale — that is the
// whole point. A 24-hour clock is zero-padded ("09:05", not "9:05") so a column
// of times in the mono face keeps one straight edge; 12-hour stays unpadded,
// which is how it reads naturally ("9:05 AM").
function clockOpts(f: TimeFormat): Intl.DateTimeFormatOptions {
  return f === '24h'
    ? { hour: '2-digit', minute: '2-digit', hour12: false }
    : { hour: 'numeric', minute: '2-digit', hour12: true }
}

/** A time of day on its own — "14:05" or "2:05 PM". */
export function fmtClock(iso: string, f: TimeFormat, locale?: string): string {
  const d = parseDate(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleTimeString(locale, clockOpts(f))
}

/** A task's due stamp: a bare date when all-day, date + time when timed. */
export function fmtDue(iso: string | null, isDate: boolean, f: TimeFormat,
                       locale?: string): string {
  if (!iso) return ''
  const d = parseDate(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString(locale,
    isDate
      ? { month: 'short', day: 'numeric' }
      : { month: 'short', day: 'numeric', ...clockOpts(f) })
}

/** A booking's "when": weekday, date and time in one line. */
export function fmtWhen(iso: string, f: TimeFormat, locale?: string): string {
  const d = parseDate(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString(locale,
    { weekday: 'short', month: 'short', day: 'numeric', ...clockOpts(f) })
}

/**
 * The `lang` a native `<input type="time">` / `datetime-local` should carry.
 *
 * Those controls are drawn by the browser, not by us, so no CSS or JS of ours
 * decides whether they show AM/PM. Chromium — and so WebView2, which the
 * Windows client embeds — reads the element's `lang` to pick the clock, which
 * makes this the only lever there is. Firefox ignores it and follows the OS
 * locale; there is no supported override short of replacing the controls with
 * hand-built pickers, so the setting's hint text says as much rather than
 * promising something that only holds in some browsers.
 *
 * It carries the LANGUAGE too, because the same attribute names the month the
 * date picker's calendar spells out. An account reading German everywhere else
 * and "September" in the one popup would be the seam showing.
 *
 * Two ways to state the clock, and which one applies is a fact about the
 * language rather than a preference:
 *
 *   * A REGION whose everyday clock is already the one wanted. en-US is a
 *     12-hour place and en-GB a 24-hour one, so English needs no extension and
 *     — this is the part worth keeping — degrades correctly in a browser that
 *     ignores extensions entirely.
 *   * The `-u-hc-` extension, for a language where no region will do it. Every
 *     German-speaking country runs a 24-hour clock, so `de` + 12h has nothing
 *     to pick and must ask outright. Where the browser honours it, the picker
 *     shows AM/PM; where it does not, the user gets German's own 24-hour clock,
 *     which is a sane thing to be given rather than a broken one.
 *
 * `lang` defaults to English so the callers and tests that predate the Language
 * setting keep the exact two tags they had.
 */
export function inputLang(f: TimeFormat, lang: Language = DEFAULT_LANGUAGE): string {
  if (lang === 'en') return f === '24h' ? 'en-GB' : 'en-US'
  return f === '24h' ? lang : `${lang}-u-hc-h12`
}

/**
 * A DURATION, in the compactest honest form: `45m`, `2h`, `1h 30m`.
 *
 * In this file because it is the app's other reading of a clock face, and a
 * reader looking for "how does this app render time" should find both here. It
 * deliberately does NOT consult `TimeFormat`, and that is the distinction worth
 * keeping: 12- or 24-hour is a choice about how to name an INSTANT — whether
 * 15:00 is written "3 PM" — and an hour and a half is an hour and a half on
 * either setting. Threading `tf` in would be a parameter every call site had to
 * supply and none could act on.
 *
 * Whole hours drop the minutes ("2h", not "2h 0m") because the zero says
 * nothing; sub-hour durations keep only minutes. Zero is "0m" rather than the
 * empty string, so a row that has been deliberately estimated at nothing still
 * reads as estimated — the difference between "this takes no time worth
 * counting" and "nobody has said", which the whole feature turns on.
 *
 * Negative input is clamped to 0. -1 is the wire's CLEAR sentinel
 * (`PatchDayEntryBody.estimate_minutes`) and should never reach a formatter;
 * rendering it as "-1m" would put the protocol on the screen.
 */
export function fmtDuration(minutes: number): string {
  const m = Math.max(0, Math.round(minutes))
  const h = Math.floor(m / 60)
  const rest = m % 60
  if (!h) return `${rest}m`
  return rest ? `${h}h ${rest}m` : `${h}h`
}
