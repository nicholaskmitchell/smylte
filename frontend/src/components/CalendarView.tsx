import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { api, type CalEvent, type List } from '../api'
import { makeGuard, ymd } from '../util'
import { Sidebar } from './Sidebar'

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December']

interface Draft { event?: CalEvent; date?: string }

export function CalendarView({ rev, onExpire }: { rev: number; onExpire: () => void }) {
  const guard = makeGuard(onExpire)
  const [cals, setCals] = useState<List[]>([])
  const [sel, setSel] = useState('')
  const [cursor, setCursor] = useState(() => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), 1) })
  const [events, setEvents] = useState<CalEvent[]>([])
  const [draft, setDraft] = useState<Draft | null>(null)

  const days = useMemo(() => {
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
    const start = new Date(first)
    start.setDate(first.getDate() - first.getDay())
    return Array.from({ length: 42 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d })
  }, [cursor])

  useEffect(() => {
    guard(async () => {
      const cs = await api.calendars()
      setCals(cs)
      setSel((s) => s || cs[0]?.id || '')
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rev])

  useEffect(() => {
    if (!sel) { setEvents([]); return }
    const end = new Date(days[41]); end.setDate(end.getDate() + 1)
    guard(async () => setEvents(await api.events(sel, ymd(days[0]), ymd(end))))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, cursor, rev])

  const reload = () => guard(async () => {
    const end = new Date(days[41]); end.setDate(end.getDate() + 1)
    const evs = await api.events(sel, ymd(days[0]), ymd(end)); if (evs) setEvents(evs)
  })

  const byDay = useMemo(() => {
    const m: Record<string, CalEvent[]> = {}
    for (const e of events) {
      if (!e.start) continue
      const key = e.start.slice(0, 10)
      ;(m[key] ||= []).push(e)
    }
    for (const k of Object.keys(m)) m[k].sort((a, b) => (a.start || '').localeCompare(b.start || ''))
    return m
  }, [events])

  const save = async (body: Record<string, unknown>, uid?: string) => {
    if (uid) await guard(() => api.patchEvent(sel, uid, body))
    else await guard(() => api.createEvent(sel, body))
    setDraft(null); reload()
  }
  const del = async (uid: string) => { await guard(() => api.deleteEvent(sel, uid)); setDraft(null); reload() }
  const calApi = {
    create: (name: string) => guard(() => api.createCalendar(name)),
    update: (id: string, body: { name?: string; color?: string | null }) =>
      guard(() => api.updateCalendar(id, body)),
    remove: (id: string) => guard(() => api.deleteCalendar(id)),
    reorder: (ids: string[]) => guard(() => api.reorderCalendars(ids)),
  }

  const todayKey = ymd(new Date())
  const curCal = cals.find((c) => c.id === sel)

  return (
    <div className="work">
      <Sidebar title="Calendars" placeholder="Calendar" items={cals} sel={sel}
        countOf={(c) => c.event_count} onSelect={setSel} onItems={setCals} api={calApi} />

      <div className="content">
        <div className="cal-head">
          <button className="icon-btn" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}>‹</button>
          <button className="btn ghost" onClick={() => { const n = new Date(); setCursor(new Date(n.getFullYear(), n.getMonth(), 1)) }}>Today</button>
          <button className="icon-btn" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}>›</button>
          <span className="cal-title">{MONTHS[cursor.getMonth()]} {cursor.getFullYear()}</span>
          <span className="spacer" />
          {sel && <button className="btn" onClick={() => setDraft({ date: todayKey })}>New event</button>}
        </div>
        {!sel ? (
          <div className="empty">Create a calendar to get started.</div>
        ) : (
          <div className="cal-grid"
            style={curCal?.color ? { '--ev-c': curCal.color } as CSSProperties : undefined}>
            {DOW.map((d) => <div key={d} className="cal-dow">{d}</div>)}
            {days.map((d) => {
              const key = ymd(d)
              const inMonth = d.getMonth() === cursor.getMonth()
              const dayEvents = byDay[key] || []
              return (
                <div key={key} className={`cal-cell ${inMonth ? '' : 'dim'} ${key === todayKey ? 'today' : ''}`}
                  onClick={() => setDraft({ date: key })}>
                  <span className="daynum">{d.getDate()}</span>
                  {dayEvents.slice(0, 4).map((e) => (
                    <div key={e.uid} className={`cal-ev ${e.all_day ? 'allday' : ''}`}
                      title={e.summary || ''}
                      onClick={(ev) => { ev.stopPropagation(); setDraft({ event: e }) }}>
                      {!e.all_day && e.start && (
                        <span className="t">{new Date(e.start).toLocaleTimeString([], { hour: 'numeric' })}</span>
                      )}
                      {e.summary || '(untitled)'}
                    </div>
                  ))}
                  {dayEvents.length > 4 && <span className="child-progress">+{dayEvents.length - 4} more</span>}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {draft && (
        <EventModal draft={draft} onClose={() => setDraft(null)}
          onSave={(body, uid) => save(body, uid)} onDelete={del} />
      )}
    </div>
  )
}

function EventModal({ draft, onClose, onSave, onDelete }: {
  draft: Draft; onClose: () => void
  onSave: (body: Record<string, unknown>, uid?: string) => void; onDelete: (uid: string) => void
}) {
  const e = draft.event
  const [summary, setSummary] = useState(e?.summary || '')
  const [allDay, setAllDay] = useState(e ? e.all_day : false)
  const baseDate = draft.date || (e?.start ? e.start.slice(0, 10) : ymd(new Date()))
  const [start, setStart] = useState(
    e?.start ? (e.start.includes('T') ? e.start.slice(0, 16) : e.start) : `${baseDate}T09:00`,
  )
  const [end, setEnd] = useState(
    e?.end ? (e.end.includes('T') ? e.end.slice(0, 16) : e.end) : `${baseDate}T10:00`,
  )
  const [location, setLocation] = useState(e?.location || '')
  const [description, setDescription] = useState(e?.description || '')
  const [tags, setTags] = useState((e?.tags || []).join(', '))

  // Keep start/end input formats consistent with the all-day toggle.
  const startVal = allDay ? start.slice(0, 10) : (start.includes('T') ? start : `${start}T09:00`)
  const endVal = allDay ? end.slice(0, 10) : (end.includes('T') ? end : `${end}T10:00`)

  const save = () => {
    const tagList = tags.split(',').map((s) => s.trim()).filter(Boolean)
    if (e) {
      onSave({ summary, start: startVal, end: endVal || null, location, description, tags: tagList }, e.uid)
    } else {
      onSave({ summary, all_day: allDay, start: startVal, end: allDay ? null : endVal, location, description, tags: tagList })
    }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(ev) => ev.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{e ? 'Event' : 'New event'}</span>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>
        <div className="field">
          <label className="label">Title</label>
          <input className="input" autoFocus value={summary} onChange={(ev) => setSummary(ev.target.value)} />
        </div>
        <label className="chip" style={{ alignSelf: 'flex-start', cursor: 'pointer' }}>
          <input type="checkbox" checked={allDay} onChange={(ev) => setAllDay(ev.target.checked)} /> all day
        </label>
        <div className="field-row">
          <div className="field">
            <label className="label">Start</label>
            <input className="input" type={allDay ? 'date' : 'datetime-local'} value={startVal}
              onChange={(ev) => setStart(ev.target.value)} />
          </div>
          <div className="field">
            <label className="label">End</label>
            <input className="input" type={allDay ? 'date' : 'datetime-local'} value={endVal}
              onChange={(ev) => setEnd(ev.target.value)} />
          </div>
        </div>
        <div className="field">
          <label className="label">Location</label>
          <input className="input" value={location} onChange={(ev) => setLocation(ev.target.value)} />
        </div>
        <div className="field">
          <label className="label">Notes</label>
          <textarea className="input" rows={2} value={description} onChange={(ev) => setDescription(ev.target.value)} />
        </div>
        <div className="field">
          <label className="label">Tags (comma-separated)</label>
          <input className="input" value={tags} onChange={(ev) => setTags(ev.target.value)} />
        </div>
        <div className="modal-actions">
          {e && <button className="btn ghost" onClick={() => onDelete(e.uid)}>Delete</button>}
          <span className="spacer" />
          <button className="btn" onClick={save}>Save</button>
        </div>
      </div>
    </div>
  )
}

