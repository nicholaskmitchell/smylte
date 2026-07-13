import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { api, type CalEvent, type List } from '../api'
import { dayKey, makeGuard, ymd } from '../util'

// Archive is app-level: the CalDAV collection stays on the wire, so an archived
// calendar's events are still fetchable. This modal lists archived calendars and
// lets you preview their events (read-only) or restore them.

const fmtTime = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })

const fmtMonth = (d: Date) =>
  d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' })

const fmtDay = (day: string) =>
  new Date(`${day}T00:00`).toLocaleDateString(undefined,
    { weekday: 'short', month: 'short', day: 'numeric' })

export function ArchivedCalendarsModal({ archived, onChange, onExpire, onClose }: {
  archived: string[]
  onChange: (next: string[]) => void
  onExpire: () => void
  onClose: () => void
}) {
  const guard = makeGuard(onExpire)
  const [cals, setCals] = useState<List[]>([])
  const [loaded, setLoaded] = useState(false)
  const [viewing, setViewing] = useState<List | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') (viewing ? setViewing(null) : onClose()) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [viewing, onClose])

  // Fetch the full calendar list (incl. archived — the backend never filters)
  // once, then match against the archived id set.
  useEffect(() => {
    guard(async () => { setCals(await api.calendars()); setLoaded(true) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const archivedCals = useMemo(
    () => cals.filter((c) => archived.includes(c.id)),
    [cals, archived],
  )

  const restore = (id: string) => {
    onChange(archived.filter((x) => x !== id))
    if (viewing?.id === id) setViewing(null)
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">
            {viewing ? viewing.name : 'Archived calendars'}
          </span>
          <button className="icon-btn" onClick={viewing ? () => setViewing(null) : onClose}>
            {viewing ? '‹ Back' : '✕'}
          </button>
        </div>

        {viewing
          ? <ArchivedEvents cal={viewing} onExpire={onExpire}
              onRestore={() => restore(viewing.id)} />
          : (
            <div className="arch-list">
              {!loaded ? (
                <div className="arch-empty">Loading…</div>
              ) : archivedCals.length === 0 ? (
                <div className="arch-empty">No archived calendars.</div>
              ) : archivedCals.map((c) => (
                <div key={c.id} className="arch-row">
                  <span className="swatch" style={c.color ? { background: c.color } : undefined} />
                  <span className="name">{c.name}</span>
                  <span className="count">{c.event_count}</span>
                  <button className="btn ghost" onClick={() => setViewing(c)}>View events</button>
                  <button className="btn" onClick={() => restore(c.id)}>Restore</button>
                </div>
              ))}
            </div>
          )}
      </div>
    </div>
  )
}

// A read-only agenda of one archived calendar's events over a fixed window
// (last month → next year). The collection is still live on Radicale, so this
// is a genuine fetch; editing is intentionally not offered here.
function ArchivedEvents({ cal, onExpire, onRestore }: {
  cal: List
  onExpire: () => void
  onRestore: () => void
}) {
  const guard = makeGuard(onExpire)
  const [events, setEvents] = useState<CalEvent[]>([])
  const [loaded, setLoaded] = useState(false)

  const { from, to } = useMemo(() => {
    const now = new Date()
    return {
      from: new Date(now.getFullYear(), now.getMonth() - 1, 1),
      to: new Date(now.getFullYear() + 1, now.getMonth(), 1),
    }
  }, [])

  useEffect(() => {
    guard(async () => {
      setEvents(await api.events(cal.id, ymd(from), ymd(to)))
      setLoaded(true)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cal.id])

  // Bucket by day and order chronologically.
  const days = useMemo(() => {
    const m: Record<string, CalEvent[]> = {}
    for (const e of events) {
      if (!e.start) continue
      ;(m[dayKey(e.start)] ||= []).push(e)
    }
    for (const k of Object.keys(m)) m[k].sort((a, b) => (a.start || '').localeCompare(b.start || ''))
    return Object.keys(m).sort().map((k) => [k, m[k]] as const)
  }, [events])

  return (
    <>
      <div className="arch-caption">
        Showing events {fmtMonth(from)} – {fmtMonth(to)}
        <button className="btn ghost" onClick={onRestore}>Restore calendar</button>
      </div>
      <div className="arch-events">
        {!loaded ? (
          <div className="arch-empty">Loading…</div>
        ) : days.length === 0 ? (
          <div className="arch-empty">No events in this window.</div>
        ) : days.map(([day, evs]) => (
          <div key={day} className="arch-day">
            <div className="arch-day-head">{fmtDay(day)}</div>
            {evs.map((e) => (
              <div key={e.id} className="agenda-ev"
                style={cal.color ? { '--ev-c': cal.color } as CSSProperties : undefined}>
                <span className="t">{e.all_day || e.start_is_date ? 'all day' : (e.start ? fmtTime(e.start) : '')}</span>
                <span>
                  {e.is_recurring && <span className="recur" aria-hidden="true">↻ </span>}
                  {e.summary || '(untitled)'}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </>
  )
}
