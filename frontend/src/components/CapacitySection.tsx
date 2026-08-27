// How long a day is expected to hold: one default, and seven optional
// exceptions.
//
// A section body inside the settings panel, not a dialog of its own — the panel
// column owns the scrolling, the heading and the way out, so this renders only
// its own rows. Controlled the way `TabsSection` is: the value arrives as a
// prop, changes leave through a callback, and `App.tsx` owns the write.
//
// The fields take the same two spellings the day's own capacity control does
// (`capacity.ts`) — "5h" or "300" — because there is one way to say how long
// something is in this app and it should not depend on which screen you are on.
// A stop time is deliberately NOT accepted here: "until 6pm" is a statement
// about today, and a default that meant "six hours" on Monday and "two" on
// Friday afternoon would be a setting whose value depended on when you last
// opened Settings.

import { useEffect, useState } from 'react'
import { HABIT_DAYS } from '../api'
import { capacityInput, parseCapacity } from '../capacity'
import { fmtDuration } from '../time'

/** "mon" → "Mon", derived from the token rather than looked up in a table —
 *  the same call `TodayView`'s habit chips make, and for the same reason: any
 *  table mapping these names to anything is a second copy of one the server
 *  owns. */
const label = (d: string) => d[0].toUpperCase() + d.slice(1)

export function CapacitySection({ minutes, byWeekday, onChange, onWeekdayChange }: {
  /** The account-wide default, or null for "never said". */
  minutes: number | null
  /** Sparse, keyed by the `HABIT_DAYS` names. A weekday absent from it falls
   *  through to the default. */
  byWeekday: Record<string, number>
  onChange: (next: number | null) => void
  onWeekdayChange: (next: Record<string, number>) => void
}) {
  return (
    <>
      <div className="menu-row">
        <label htmlFor="cap-default">Most days</label>
        <CapacityField id="cap-default" value={minutes} placeholder="not set"
          name="the default working day" onCommit={onChange} />
      </div>

      <div className="cap-week">
        {HABIT_DAYS.map((d) => (
          <div key={d} className="cap-day">
            <span className="cap-day-name">{label(d)}</span>
            <CapacityField id={`cap-${d}`} value={byWeekday[d] ?? null}
              // An unset weekday says it INHERITS rather than showing 0. Those
              // are different statements — "same as most days" and "I do not
              // work Sundays" — and a zero standing in for silence would make
              // the second unsayable.
              placeholder="same as most days" name={label(d)}
              onCommit={(next) => {
                const out = { ...byWeekday }
                if (next == null) delete out[d]
                else out[d] = next
                onWeekdayChange(out)
              }} />
          </div>
        ))}
      </div>

      <p className="hintline">
        Say it as <span className="mono">5h</span> or{' '}
        <span className="mono">300</span> minutes. A day you have not given a
        length is never counted against you — the Today tab simply says nothing
        about how full it is.
      </p>
    </>
  )
}

/** One capacity field: reads what is typed, shows back what is stored. */
function CapacityField({ id, value, placeholder, name, onCommit }: {
  id: string
  value: number | null
  placeholder: string
  /** What this sets, for the field's accessible name. */
  name: string
  onCommit: (next: number | null) => void
}) {
  const [draft, setDraft] = useState(() => capacityInput(value))
  // Follow the value when it changes UNDERNEATH — a rejected settings write
  // leaves the old number in place, and another device can change it — so a
  // stale draft cannot be committed over a newer value on the next blur. Same
  // shape, same reason, as `HabitEditRow`'s title.
  useEffect(() => { setDraft(capacityInput(value)) }, [value])

  const commit = () => {
    const raw = draft.trim()
    // An emptied field CLEARS, which is the only way back to "never said" and
    // the reason the wire needed a sentinel for it.
    if (!raw) { if (value != null) onCommit(null); return }
    // `stopTime: false` is what makes the header's promise true. The signature is
    // shared with the day's control, which DOES take "until 6pm" — and this
    // field used to take it as well, storing the interval from whenever Settings
    // happened to be open: 90 minutes at 16:30, 540 at 09:00, as the
    // account-wide default for every day of the week. The clock is still handed
    // over because the signature is shared; with the stop grammar refused it is
    // now genuinely unused here.
    const next = parseCapacity(raw, new Date(), { stopTime: false })
    // A line the parser cannot read snaps back rather than clearing. Clearing on
    // a typo would silently delete a setting the owner was in the middle of
    // editing, which is the one outcome worse than doing nothing.
    if (next == null) { setDraft(capacityInput(value)); return }
    if (next !== value) onCommit(next)
    setDraft(capacityInput(next))
  }

  return (
    <input id={id} className="input cap-input" value={draft}
      placeholder={placeholder} aria-label={`Working time for ${name}`}
      // The stored value in words, for anyone who cannot see the field snap
      // back to "5h" after typing "300".
      title={value == null ? placeholder : fmtDuration(value)}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit() }
        // Escape abandons the edit. It does NOT close the settings sheet from
        // under a half-typed number — `useEscape` is bound to the window, so
        // the propagation stop is what keeps the two from fighting.
        if (e.key === 'Escape') {
          e.preventDefault(); e.stopPropagation(); setDraft(capacityInput(value))
        }
      }} />
  )
}
