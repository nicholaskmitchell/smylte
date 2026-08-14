// One day's events, as a row and as an anchored popover. Shared by the Calendar
// tab (behind the desktop "+N more", where a row opens the editor) and the Home
// mini calendar (where a day click opens a read-only list) — passing no `onOpen`
// is what makes it read-only, so the dashboard never grows an event editor.

import { useEffect, type CSSProperties } from 'react'
import type { CalEvent } from '../api'
import type { DayEv } from '../calendar'
import { dayKey } from '../util'
import { fmtClock, type TimeFormat } from '../time'
import { useTimeFormat } from '../timeformat'

/** The time label for an event as it appears on `day`: a continuation day shows
 *  the end time if the span finishes that day, and otherwise reads as all day. */
function label(ev: DayEv, day: string, f: TimeFormat): string {
  if (ev.all_day) return 'all day'
  if (ev.cont) {
    return ev.end && !ev.end_is_date && dayKey(ev.end) === day
      ? `– ${fmtClock(ev.end, f)}`
      : 'all day'
  }
  return ev.start ? fmtClock(ev.start, f) : ''
}

export function AgendaEvent({ ev, day, style, onOpen }: {
  ev: DayEv
  day: string
  style?: CSSProperties
  onOpen?: (e: CalEvent) => void
}) {
  const tf = useTimeFormat()
  const body = (
    <>
      <span className="t">{label(ev, day, tf)}</span>
      <span>
        {ev.is_recurring && <span className="recur" aria-hidden="true">↻ </span>}
        {ev.summary || '(untitled)'}
      </span>
    </>
  )
  if (!onOpen) return <div className="agenda-ev static" style={style}>{body}</div>
  return (
    <button className="agenda-ev" style={style} onClick={() => onOpen(ev)}>{body}</button>
  )
}

// Anchored day popover — the full event list for one cell, since a cell itself
// shows at most a few rows.
export function DayPopover({ day, x, y, events, styleOf, onOpen, onClose }: {
  day: string; x: number; y: number; events: DayEv[]
  styleOf: (e: CalEvent) => CSSProperties | undefined
  onOpen?: (e: CalEvent) => void
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const long = new Date(`${day}T00:00`).toLocaleDateString(undefined,
    { weekday: 'long', month: 'long', day: 'numeric' })
  // Clamp to the viewport so edge cells don't push the popover off-screen.
  const left = Math.max(8, Math.min(x, window.innerWidth - 268))
  const top = Math.max(8, Math.min(y, window.innerHeight - 328))
  return (
    <div className="pop-backdrop" onClick={onClose}>
      <div className="day-pop" style={{ left, top }} onClick={(ev) => ev.stopPropagation()}
        role="dialog" aria-label={long}>
        <div className="day-pop-head">
          {new Date(`${day}T00:00`).toLocaleDateString(undefined,
            { weekday: 'short', month: 'short', day: 'numeric' })}
        </div>
        {events.map((e) => (
          <AgendaEvent key={e.id} ev={e} day={day} style={styleOf(e)} onOpen={onOpen} />
        ))}
      </div>
    </div>
  )
}
