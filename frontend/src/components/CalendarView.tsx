import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { api, type CalEvent, type EventScope, type List } from '../api'
import { addDays, makeGuard, pad, ymd } from '../util'
import { useIsMobile } from '../hooks'
import { Sidebar } from './Sidebar'

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December']

interface Draft { event?: CalEvent; date?: string }

// A calendar-cell entry: `cont` marks days after the first of a multi-day span.
type DayEv = CalEvent & { cont?: boolean }

const shiftYmd = (day: string, n: number) => ymd(addDays(new Date(`${day}T00:00`), n))

// Last visible day of an event. DTEND is exclusive for all-day events, and a
// timed event ending exactly at midnight shouldn't spill into the next day.
function lastDayOf(e: CalEvent): string {
  const startDay = e.start!.slice(0, 10)
  if (!e.end) return startDay
  const endDay = e.end.slice(0, 10)
  const exclusive = e.end_is_date || e.end.slice(11, 16) === '00:00'
  const last = exclusive ? shiftYmd(endDay, -1) : endDay
  return last < startDay ? startDay : last
}

export function CalendarView({ rev, onExpire, sideCollapsed, onToggleSide }: {
  rev: number; onExpire: () => void
  sideCollapsed: boolean; onToggleSide: () => void
}) {
  const guard = makeGuard(onExpire)
  const isMobile = useIsMobile()
  const [cals, setCals] = useState<List[]>([])
  const [sel, setSel] = useState('')
  const [cursor, setCursor] = useState(() => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), 1) })
  const [events, setEvents] = useState<CalEvent[]>([])
  const [draft, setDraft] = useState<Draft | null>(null)
  // Mobile shows a day agenda under the grid; this is the day it follows.
  const [focusDay, setFocusDay] = useState(() => ymd(new Date()))

  // Keep the focused day inside the visible month when the user navigates.
  useEffect(() => {
    const monthKey = `${cursor.getFullYear()}-${pad(cursor.getMonth() + 1)}`
    setFocusDay((f) => {
      if (f.slice(0, 7) === monthKey) return f
      const today = ymd(new Date())
      return today.slice(0, 7) === monthKey ? today : `${monthKey}-01`
    })
  }, [cursor])

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
    const m: Record<string, DayEv[]> = {}
    const first = ymd(days[0])
    const last = ymd(days[41])
    for (const e of events) {
      if (!e.start) continue
      const startDay = e.start.slice(0, 10)
      const endDay = lastDayOf(e)
      // Walk every day the event covers, clipped to the visible 6-week window.
      let day = startDay < first ? first : startDay
      const stop = endDay > last ? last : endDay
      for (let i = 0; day <= stop && i < 42; i++, day = shiftYmd(day, 1)) {
        ;(m[day] ||= []).push(day === startDay ? e : { ...e, cont: true })
      }
    }
    for (const k of Object.keys(m)) m[k].sort((a, b) => (a.start || '').localeCompare(b.start || ''))
    return m
  }, [events, days])

  const save = async (body: Record<string, unknown>, uid?: string) => {
    if (uid) await guard(() => api.patchEvent(sel, uid, body))
    else await guard(() => api.createEvent(sel, body))
    setDraft(null); reload()
  }
  const del = async (uid: string, opts?: { recurrence_id?: string | null; scope?: EventScope }) => {
    await guard(() => api.deleteEvent(sel, uid, opts)); setDraft(null); reload()
  }
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
        countOf={(c) => c.event_count} onSelect={setSel} onItems={setCals} api={calApi}
        collapsed={sideCollapsed} onToggle={onToggleSide} />

      <div className="content">
        <div className="cal-head">
          <button className="icon-btn" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}>‹</button>
          <button className="btn ghost" onClick={() => { const n = new Date(); setCursor(new Date(n.getFullYear(), n.getMonth(), 1)) }}>Today</button>
          <button className="icon-btn" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}>›</button>
          <span className="cal-title">{MONTHS[cursor.getMonth()]} {cursor.getFullYear()}</span>
          <span className="spacer" />
          {sel && !isMobile && <button className="btn" onClick={() => setDraft({ date: todayKey })}>New event</button>}
        </div>
        {!sel ? (
          <div className="empty">Create a calendar to get started.</div>
        ) : (
          <div className="cal-scroll"
            style={curCal?.color ? { '--ev-c': curCal.color } as CSSProperties : undefined}>
            <div className="cal-grid">
              {DOW.map((d) => <div key={d} className="cal-dow">{d}</div>)}
              {days.map((d) => {
                const key = ymd(d)
                const inMonth = d.getMonth() === cursor.getMonth()
                const dayEvents = byDay[key] || []
                return (
                  <div key={key}
                    className={`cal-cell ${inMonth ? '' : 'dim'} ${key === todayKey ? 'today' : ''} ${isMobile && key === focusDay ? 'focus' : ''}`}
                    onClick={() => {
                      // Mobile: first tap focuses the day in the agenda; a second
                      // tap on the focused day (or the agenda's button) creates.
                      if (isMobile && key !== focusDay) setFocusDay(key)
                      else setDraft({ date: key })
                    }}>
                    <span className="daynum">{d.getDate()}</span>
                    {isMobile ? (
                      dayEvents.length > 0 && (
                        <span className="ev-dots">
                          {dayEvents.slice(0, 6).map((e) => (
                            <i key={e.id} className={`ev-dot ${e.all_day ? 'allday' : ''}`} />
                          ))}
                        </span>
                      )
                    ) : (
                      <>
                        {dayEvents.slice(0, 4).map((e) => (
                          <div key={e.id} className={`cal-ev ${e.all_day ? 'allday' : ''} ${e.cont ? 'cont' : ''}`}
                            title={e.is_recurring ? `${e.summary || ''} (repeating)` : (e.summary || '')}
                            onClick={(ev) => { ev.stopPropagation(); setDraft({ event: e }) }}>
                            {!e.all_day && e.start && !e.cont && (
                              <span className="t">{new Date(e.start).toLocaleTimeString([], { hour: 'numeric' })}</span>
                            )}
                            {e.is_recurring && <span className="recur" aria-hidden="true">↻ </span>}
                            {e.cont && <span className="t" aria-hidden="true">‥ </span>}
                            {e.summary || '(untitled)'}
                          </div>
                        ))}
                        {dayEvents.length > 4 && <span className="child-progress">+{dayEvents.length - 4} more</span>}
                      </>
                    )}
                  </div>
                )
              })}
            </div>
            {isMobile && (
              <div className="day-agenda">
                <div className="agenda-head">
                  <span className="label">
                    {new Date(`${focusDay}T00:00`).toLocaleDateString(undefined,
                      { weekday: 'long', month: 'long', day: 'numeric' })}
                  </span>
                  <button className="btn" onClick={() => setDraft({ date: focusDay })}>+ Event</button>
                </div>
                {(byDay[focusDay] || []).map((e) => (
                  <button key={e.id} className="agenda-ev" onClick={() => setDraft({ event: e })}>
                    <span className="t">
                      {e.all_day ? 'all day'
                        : e.cont
                          ? (e.end && !e.end_is_date && e.end.slice(0, 10) === focusDay
                            ? `– ${new Date(e.end).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
                            : 'all day')
                          : e.start
                            ? new Date(e.start).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
                            : ''}
                    </span>
                    <span>
                      {e.is_recurring && <span className="recur" aria-hidden="true">↻ </span>}
                      {e.summary || '(untitled)'}
                    </span>
                  </button>
                ))}
                {(byDay[focusDay] || []).length === 0 && (
                  <div className="agenda-empty">No events this day.</div>
                )}
              </div>
            )}
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

const REPEATS: ReadonlyArray<readonly [string, string]> = [
  ['none', 'Does not repeat'], ['daily', 'Daily'], ['weekly', 'Weekly'],
  ['monthly', 'Monthly'], ['yearly', 'Yearly'],
]

function EventModal({ draft, onClose, onSave, onDelete }: {
  draft: Draft; onClose: () => void
  onSave: (body: Record<string, unknown>, uid?: string) => void
  onDelete: (uid: string, opts?: { recurrence_id?: string | null; scope?: EventScope }) => void
}) {
  const e = draft.event
  const recurring = !!e?.is_recurring
  const [summary, setSummary] = useState(e?.summary || '')
  const [allDay, setAllDay] = useState(e ? e.all_day : false)
  const baseDate = draft.date || (e?.start ? e.start.slice(0, 10) : ymd(new Date()))
  const [start, setStart] = useState(
    e?.start ? (e.start.includes('T') ? e.start.slice(0, 16) : e.start) : `${baseDate}T09:00`,
  )
  const [end, setEnd] = useState(() => {
    if (!e?.end) return `${baseDate}T10:00`
    if (e.end.includes('T')) return e.end.slice(0, 16)
    // All-day DTEND is exclusive — show the inclusive last day in the picker.
    const inclusive = shiftYmd(e.end.slice(0, 10), -1)
    const startDay = e.start ? e.start.slice(0, 10) : inclusive
    return inclusive < startDay ? startDay : inclusive
  })
  const [location, setLocation] = useState(e?.location || '')
  const [description, setDescription] = useState(e?.description || '')
  const [tags, setTags] = useState((e?.tags || []).join(', '))
  // A new/non-recurring event picks a concrete cadence; an existing recurring one
  // defaults to "keep" — we don't surface its exact FREQ, so leaving it untouched
  // preserves the rule.
  const [repeat, setRepeat] = useState<string>(recurring ? 'keep' : 'none')
  const [repeatUntil, setRepeatUntil] = useState('')
  const [scopeAsk, setScopeAsk] = useState<null | 'save' | 'delete'>(null)

  // Keep start/end input formats consistent with the all-day toggle.
  const startVal = allDay ? start.slice(0, 10) : (start.includes('T') ? start : `${start}T09:00`)
  const endVal = allDay ? end.slice(0, 10) : (end.includes('T') ? end : `${end}T10:00`)

  // Moving the start drags the end along, preserving the event's duration — no
  // more fixing the end by hand after every start change.
  const changeStart = (v: string) => {
    setStart(v)
    if (!v) return
    const oldS = new Date(allDay ? `${startVal}T00:00` : startVal)
    const oldE = new Date(allDay ? `${endVal}T00:00` : endVal)
    const newS = new Date(allDay ? `${v}T00:00` : v)
    if (isNaN(oldS.getTime()) || isNaN(oldE.getTime()) || isNaN(newS.getTime())) return
    const shifted = new Date(newS.getTime() + Math.max(0, oldE.getTime() - oldS.getTime()))
    setEnd(allDay ? ymd(shifted)
      : `${ymd(shifted)}T${pad(shifted.getHours())}:${pad(shifted.getMinutes())}`)
  }

  // What actually goes on the wire: end never precedes start, and an all-day
  // range converts back from the inclusive picker to an exclusive DTEND.
  const clampedEnd = endVal < startVal ? startVal : endVal
  const startOut = startVal
  const endOut = allDay ? shiftYmd(clampedEnd, 1) : clampedEnd

  const tagList = () => tags.split(',').map((s) => s.trim()).filter(Boolean)
  const repeatFields = (): Record<string, unknown> => {
    if (repeat === 'keep') return {}          // leave the existing rule untouched
    const b: Record<string, unknown> = { repeat }
    if (repeat !== 'none' && repeatUntil) b.repeat_until = repeatUntil
    return b
  }

  const commit = (scope: EventScope) => {
    if (!e) {
      onSave({ summary, all_day: allDay, start: startOut, end: endOut,
               location, description, tags: tagList(), ...repeatFields() })
      return
    }
    const details = { summary, location, description, tags: tagList() }
    if (recurring && scope === 'all') {
      // Edit-safety: never resend an occurrence's start/end as the series master
      // start (that would slide the whole series). "All events" edits details and
      // the repeat rule only; move a single instance with "This event".
      onSave({ ...details, ...repeatFields(), scope: 'all' }, e.uid)
    } else if (recurring) {
      onSave({ ...details, start: startOut, end: endOut,
               recurrence_id: e.recurrence_id, scope }, e.uid)
    } else {
      onSave({ ...details, start: startOut, end: endOut, ...repeatFields() }, e.uid)
    }
  }

  const onSaveClick = () => { if (recurring) setScopeAsk('save'); else commit('all') }
  const onDeleteClick = () => { if (!e) return; recurring ? setScopeAsk('delete') : onDelete(e.uid) }
  const pickScope = (scope: EventScope) => {
    if (scopeAsk === 'delete' && e) onDelete(e.uid, { recurrence_id: e.recurrence_id, scope })
    else commit(scope)
    setScopeAsk(null)
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(ev) => ev.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{e ? (recurring ? 'Repeating event' : 'Event') : 'New event'}</span>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>

        {scopeAsk ? (
          <div className="scope-choose">
            <p className="scope-q">
              {scopeAsk === 'delete' ? 'Delete which events?' : 'Apply changes to which events?'}
            </p>
            <button className="btn" onClick={() => pickScope('this')}>This event</button>
            <button className="btn" onClick={() => pickScope('thisandfuture')}>This &amp; following</button>
            <button className="btn" onClick={() => pickScope('all')}>All events</button>
            <button className="btn ghost" onClick={() => setScopeAsk(null)}>Cancel</button>
          </div>
        ) : (
          <>
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
                  onChange={(ev) => changeStart(ev.target.value)} />
              </div>
              <div className="field">
                <label className="label">{allDay ? 'End (last day)' : 'End'}</label>
                <input className="input" type={allDay ? 'date' : 'datetime-local'} value={endVal}
                  min={startVal} onChange={(ev) => setEnd(ev.target.value)} />
              </div>
            </div>
            <div className="field">
              <label className="label">Repeat</label>
              <select className="input" value={repeat} onChange={(ev) => setRepeat(ev.target.value)}>
                {recurring && <option value="keep">Keep current schedule</option>}
                {REPEATS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            {repeat !== 'keep' && repeat !== 'none' && (
              <div className="field">
                <label className="label">Repeat until (optional)</label>
                <input className="input" type="date" value={repeatUntil}
                  onChange={(ev) => setRepeatUntil(ev.target.value)} />
              </div>
            )}
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
            {recurring && (
              <p className="scope-hint">
                “All events” changes details &amp; repeat only — use “This event” to move a single occurrence.
              </p>
            )}
            <div className="modal-actions">
              {e && <button className="btn ghost" onClick={onDeleteClick}>Delete</button>}
              <span className="spacer" />
              <button className="btn" onClick={onSaveClick}>Save</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

