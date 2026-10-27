// What a share link looks like to its owner, kept free of React so the Settings
// section and the Home module say the same thing about the same link.
import type { Share } from './api'
import type { Vars } from './i18n/index'
import { fmtWhen, type TimeFormat } from './time'
import { parseDate } from './util'

// How recently a link must have been opened to count as open right now. The
// page polls every 15 to 30 seconds, and the server stamps `last_seen_at` at
// most once a minute, so two minutes is the shortest window that does not
// flicker to "last opened" between two stamps of a page that is still on screen.
export const OPEN_NOW_MS = 120_000

// The state the owner should SEE. The DTO already reports `enabled` false for
// a link a password change switched off, but the two are combined here as well
// so the toggle never reads On beside the sentence that says it is off.
export function isOn(d: Share): boolean {
  return d.enabled && !d.switched_off_by_password
}

/** Whether somebody had the link open at `nowMs`. The clock is a parameter so a
 *  caller that ticks on a timer can age this out without a fetch. */
export function openNow(d: Share, nowMs: number): boolean {
  return d.last_seen_at !== null && nowMs - parseDate(d.last_seen_at).getTime() < OPEN_NOW_MS
}

/** "Open now", "Last opened …" or "Not opened yet". */
export function seenText(
  d: Share, nowMs: number, tr: (k: string, v?: Vars) => string, tf: TimeFormat, locale: string,
): string {
  if (openNow(d, nowMs)) return tr('shares.openNow')
  if (d.last_seen_at) return tr('shares.lastSeen', { when: fmtWhen(d.last_seen_at, tf, locale) })
  return tr('shares.neverSeen')
}
