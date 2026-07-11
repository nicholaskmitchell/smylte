import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { api, type CalEvent, type EventScope, type List } from '../api'
import { addDays, dayKey, makeGuard, pad, parseDate, toLocalInput, ymd } from '../util'
import { useIsMobile } from '../hooks'
import { ALL_ID, Sidebar } from './Sidebar'

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December']

interface Draft { event?: CalEvent; date?: string }

// A calendar-cell entry: `cont` marks days after the first of a multi-day span.
type DayEv = CalEvent & { cont?: boolean }

const shiftYmd = (day: string, n: number) => ymd(addDays(new Date(`${day}T00:00`), n))

const daysBetween = (a: string, b: string) =>
  Math.round((new Date(`${b}T00:00`).getTime() - new Date(`${a}T00:00`).getTime()) / 86400000)

// Shift an ISO date or datetime by n days. Datetimes come back as floating
// local wall time — the same form the edit modal writes.
const shiftIso = (v: string, n: number) => {
  if (!v.includes('T')) return shiftYmd(v, n)
  const d = addDays(parseDate(v), n)
  return `${ymd(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// Last visible day of an event. DTEND is exclusive for all-day events, and a
// timed event ending exactly at midnight shouldn't spill into the next day.
// Days come from dayKey/parseDate so events written with a UTC offset (e.g. by
// another CalDAV client) land on the viewer's local day.
function lastDayOf(e: CalEvent): string {
  const startDay = dayKey(e.start!)
  if (!e.end) return startDay
  const end = parseDate(e.end)
  const endDay = ymd(end)
  const exclusive = e.end_is_date ||
    (e.end.includes('T') && end.getHours() === 0 && end.getMinutes() === 0)
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
      // Land on the combined view when there is more than one calendar, and
      // fall back to a real one when the selection disappears (or the All row
      // does, once a deletion leaves a single calendar behind).
      setSel((s) => {
        const fallback = cs.length > 1 ? ALL_ID : cs[0]?.id || ''
        if (!s || (s === ALL_ID && cs.length <= 1)) return fallback
        if (s !== ALL_ID && !cs.some((c) => c.id === s)) return fallback
        return s
      })
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rev])

  // The combined view merges every calendar's window; events carry their
  // collection href, so each one still knows where it lives.
  const fetchEvents = async (): Promise<CalEvent[]> => {
    const end = new Date(days[41]); end.setDate(end.getDate() + 1)
    const from = ymd(days[0]); const to = ymd(end)
    if (sel !== ALL_ID) return api.events(sel, from, to)
    const per = await Promise.all(cals.map((c) => api.events(c.id, from, to)))
    return per.flat()
  }

  const calsKey = cals.map((c) => c.id).join(',')
  useEffect(() => {
    if (!sel || (sel === ALL_ID && !cals.length)) { setEvents([]); return }
    guard(async () => setEvents(await fetchEvents()))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, cursor, rev, calsKey])

  const reload = () => guard(async () => {
    const evs = await fetchEvents(); if (evs) setEvents(evs)
  })

  const calByHref = useMemo(() => new Map(cals.map((c) => [c.href, c] as const)), [cals])
  // Which calendar an event lives in (the selection itself outside the All view).
  const calIdOf = (e: CalEvent) => calByHref.get(e.calendar)?.id || (sel === ALL_ID ? '' : sel)
  // Per-event tint, so the combined view keeps each calendar's color.
  const evStyle = (e: CalEvent): CSSProperties | undefined => {
    const c = calByHref.get(e.calendar)?.color
    return c ? { '--ev-c': c } as CSSProperties : undefined
  }

  const byDay = useMemo(() => {
    const m: Record<string, DayEv[]> = {}
    const first = ymd(days[0])
    const last = ymd(days[41])
    for (const e of events) {
      if (!e.start) continue
      const startDay = dayKey(e.start)
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

  // Optimistically paint an edit onto the events we can represent locally: a
  // non-recurring event, or a single occurrence (scope "this"). Series-wide
  // edits return false — the caller reloads for those instead.
  const applyLocal = (uid: string, body: Record<string, unknown>): boolean => {
    const single = body.scope === 'this' && !!body.recurrence_id
    if (!single && events.some((e) => e.uid === uid && e.is_recurring)) return false
    setEvents((evs) => evs.map((e) => {
      if (e.uid !== uid) return e
      if (single && e.id !== `${uid}::${body.recurrence_id}`) return e
      const n = { ...e }
      if (typeof body.summary === 'string') n.summary = body.summary
      if (typeof body.location === 'string') n.location = body.location
      if (typeof body.description === 'string') n.description = body.description
      if (Array.isArray(body.tags)) n.tags = body.tags as string[]
      if (typeof body.start === 'string') {
        n.start = body.start
        n.start_is_date = !body.start.includes('T')
        n.all_day = n.start_is_date
      }
      if (typeof body.end === 'string') {
        n.end = body.end
        n.end_is_date = !body.end.includes('T')
      }
      return n
    }))
    return true
  }

  // Create in `cal`, or patch `uid` there — then relocate the resource if the
  // modal picked a different calendar. The modal closes and the grid updates
  // immediately; the request settles behind, and a reload reconciles whenever
  // the local paint can't be exact (series edits, moves) or the write failed.
  const save = async (body: Record<string, unknown>, cal: string, uid?: string, moveTo?: string) => {
    setDraft(null)
    if (!uid) {
      const created = await guard(() => api.createEvent(cal, body))
      if (!created) return
      if (created.is_recurring) reload()          // occurrences expand server-side
      else setEvents((evs) => [...evs, created])
      return
    }
    const painted = applyLocal(uid, body)
    const ok = await guard(() => api.patchEvent(cal, uid, body))
    const moved = !!(ok && moveTo && moveTo !== cal)
    if (moved) await guard(() => api.moveEvent(cal, uid, moveTo!))
    if (!ok || !painted || moved) reload()
  }
  const del = async (cal: string, uid: string, opts?: { recurrence_id?: string | null; scope?: EventScope }) => {
    setDraft(null)
    // Drop the affected instances right away; reload rolls back on failure.
    const rid = opts?.recurrence_id
    const scope = opts?.scope || 'all'
    setEvents((evs) => evs.filter((e) => {
      if (e.uid !== uid) return true
      if (scope === 'this' && rid) return e.id !== `${uid}::${rid}`
      if (scope === 'thisandfuture' && rid) return (e.recurrence_id || '') < rid
      return false
    }))
    if ((await guard(() => api.deleteEvent(cal, uid, opts))) === undefined) reload()
  }

  // Desktop drag: move an event chip to another day cell, or drag its resize
  // grip to a new last day. A recurring drop parks in `moveAsk` until the user
  // picks a scope; delta is anchored to the dragged segment's own cell, so
  // continuation segments (and window-clipped events) move correctly.
  const [drag, setDrag] = useState<{ ev: DayEv; fromDay: string; mode: 'move' | 'resize' } | null>(null)
  const [overDay, setOverDay] = useState<string | null>(null)
  const [moveAsk, setMoveAsk] = useState<{ ev: CalEvent; body: Record<string, unknown> } | null>(null)

  const dropOnDay = (key: string) => {
    const d = drag
    setDrag(null); setOverDay(null)
    if (!d?.ev.start) return
    let body: Record<string, unknown>
    if (d.mode === 'move') {
      const delta = daysBetween(d.fromDay, key)
      if (!delta) return
      body = { start: shiftIso(d.ev.start, delta) }
      if (d.ev.end) body.end = shiftIso(d.ev.end, delta)
    } else {
      const startDay = dayKey(d.ev.start)
      const day = key < startDay ? startDay : key
      const start = d.ev.all_day ? d.ev.start.slice(0, 10) : toLocalInput(d.ev.start)
      let end: string
      if (d.ev.all_day) {
        end = shiftYmd(day, 1)              // DTEND stays exclusive
      } else {
        end = `${day}T${toLocalInput(d.ev.end || d.ev.start).slice(11, 16)}`
        if (end <= start) return            // the end must stay after the start
      }
      const oldEnd = d.ev.end && (d.ev.all_day ? d.ev.end.slice(0, 10) : toLocalInput(d.ev.end))
      if (end === oldEnd) return
      body = { start, end }
    }
    if (d.ev.is_recurring) setMoveAsk({ ev: d.ev, body })
    else save(body, calIdOf(d.ev), d.ev.uid)
  }
  const pickMoveScope = (scope: EventScope) => {
    if (!moveAsk) return
    save({ ...moveAsk.body, recurrence_id: moveAsk.ev.recurrence_id, scope },
      calIdOf(moveAsk.ev), moveAsk.ev.uid)
    setMoveAsk(null)
  }

  // Desktop "+N more": a popover anchored to the day cell listing every event.
  const [more, setMore] = useState<{ day: string; x: number; y: number } | null>(null)
  const calApi = {
    create: (name: string) => guard(() => api.createCalendar(name)),
    update: (id: string, body: { name?: string; color?: string | null }) =>
      guard(() => api.updateCalendar(id, body)),
    remove: (id: string) => guard(() => api.deleteCalendar(id)),
    reorder: (ids: string[]) => guard(() => api.reorderCalendars(ids)),
  }

  const todayKey = ymd(new Date())
  const lastKey = ymd(days[41])            // final visible day, for resize grips
  const curCal = cals.find((c) => c.id === sel)

  return (
    <div className="work">
      <Sidebar title="Calendars" placeholder="Calendar" items={cals} sel={sel}
        countOf={(c) => c.event_count} onSelect={setSel} onItems={setCals} api={calApi}
        collapsed={sideCollapsed} onToggle={onToggleSide} allLabel="All calendars" />

      <div className="content">
        <div className="cal-head">
          <button className="icon-btn" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}>‹</button>
          <button className="btn ghost" onClick={() => { const n = new Date(); setCursor(new Date(n.getFullYear(), n.getMonth(), 1)) }}>Today</button>
          <button className="icon-btn" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}>›</button>
          <span className="cal-title">{MONTHS[cursor.getMonth()]} {cursor.getFullYear()}</span>
          <span className="spacer" />
          {sel && cals.length > 0 && !isMobile && (
            <button className="btn" onClick={() => setDraft({ date: todayKey })}>New event</button>
          )}
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
                    className={`cal-cell ${inMonth ? '' : 'dim'} ${key === todayKey ? 'today' : ''} ${isMobile && key === focusDay ? 'focus' : ''} ${drag && overDay === key ? 'drag-over' : ''}`}
                    onDragOver={(ev) => { if (!drag) return; ev.preventDefault(); setOverDay(key) }}
                    onDragLeave={() => setOverDay((o) => (o === key ? null : o))}
                    onDrop={(ev) => { ev.preventDefault(); dropOnDay(key) }}
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
                            <i key={e.id} className={`ev-dot ${e.all_day ? 'allday' : ''}`} style={evStyle(e)} />
                          ))}
                        </span>
                      )
                    ) : (
                      <>
                        {dayEvents.slice(0, 4).map((e) => {
                          const evLast = lastDayOf(e)
                          const resizable = key === (evLast > lastKey ? lastKey : evLast)
                          return (
                            <div key={e.id} className={`cal-ev ${e.all_day ? 'allday' : ''} ${e.cont ? 'cont' : ''}`}
                              style={evStyle(e)}
                              title={e.is_recurring ? `${e.summary || ''} (repeating)` : (e.summary || '')}
                              draggable
                              onDragStart={(ev) => {
                                ev.stopPropagation()
                                ev.dataTransfer.setData('text/plain', e.id)  // Firefox needs data to start a drag
                                ev.dataTransfer.effectAllowed = 'move'
                                setDrag({ ev: e, fromDay: key, mode: 'move' })
                              }}
                              onDragEnd={() => { setDrag(null); setOverDay(null) }}
                              onClick={(ev) => { ev.stopPropagation(); setDraft({ event: e }) }}>
                              {!e.all_day && e.start && !e.cont && (
                                <span className="t">{new Date(e.start).toLocaleTimeString([], { hour: 'numeric' })}</span>
                              )}
                              {e.is_recurring && <span className="recur" aria-hidden="true">↻ </span>}
                              {e.cont && <span className="t" aria-hidden="true">‥ </span>}
                              {e.summary || '(untitled)'}
                              {resizable && (
                                <span className="ev-resize" title="Drag to change the last day"
                                  draggable
                                  onDragStart={(ev) => {
                                    ev.stopPropagation()
                                    ev.dataTransfer.setData('text/plain', e.id)
                                    ev.dataTransfer.effectAllowed = 'move'
                                    setDrag({ ev: e, fromDay: key, mode: 'resize' })
                                  }} />
                              )}
                            </div>
                          )
                        })}
                        {dayEvents.length > 4 && (
                          <button className="cal-more" onClick={(ev) => {
                            ev.stopPropagation()
                            const r = ev.currentTarget.closest('.cal-cell')!.getBoundingClientRect()
                            setMore({ day: key, x: r.left, y: r.top })
                          }}>+{dayEvents.length - 4} more</button>
                        )}
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
                  <button key={e.id} className="agenda-ev" style={evStyle(e)}
                    onClick={() => setDraft({ event: e })}>
                    <span className="t">
                      {e.all_day ? 'all day'
                        : e.cont
                          ? (e.end && !e.end_is_date && dayKey(e.end) === focusDay
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
        <EventModal draft={draft} cals={cals} onClose={() => setDraft(null)}
          initialCal={draft.event ? calIdOf(draft.event) : (sel === ALL_ID ? cals[0]?.id || '' : sel)}
          onSave={(body, cal, uid) => {
            // Existing events are patched where they live, then relocated if a
            // different calendar was picked; new events go straight to the pick.
            if (uid && draft.event) save(body, calIdOf(draft.event), uid, cal)
            else save(body, cal)
          }}
          onDelete={(uid, opts) => del(draft.event ? calIdOf(draft.event) : sel, uid, opts)} />
      )}

      {more && (
        <DayPopover day={more.day} x={more.x} y={more.y} events={byDay[more.day] || []}
          styleOf={evStyle}
          onOpen={(e) => { setMore(null); setDraft({ event: e }) }}
          onClose={() => setMore(null)} />
      )}

      {moveAsk && (
        <div className="overlay" onClick={() => setMoveAsk(null)}>
          <div className="modal" onClick={(ev) => ev.stopPropagation()}>
            <div className="modal-head">
              <span className="modal-title">Repeating event</span>
              <button className="icon-btn" onClick={() => setMoveAsk(null)}>✕</button>
            </div>
            <div className="scope-choose">
              <p className="scope-q">Apply the change to which events?</p>
              <button className="btn" onClick={() => pickMoveScope('this')}>This event</button>
              <button className="btn" onClick={() => pickMoveScope('thisandfuture')}>This &amp; following</button>
              <button className="btn" onClick={() => pickMoveScope('all')}>All events</button>
              <button className="btn ghost" onClick={() => setMoveAsk(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// Anchored day popover behind the desktop "+N more" — the full event list for
// one cell, since the cell itself shows at most four rows.
function DayPopover({ day, x, y, events, styleOf, onOpen, onClose }: {
  day: string; x: number; y: number; events: DayEv[]
  styleOf: (e: CalEvent) => CSSProperties | undefined
  onOpen: (e: CalEvent) => void; onClose: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  // Clamp to the viewport so edge cells don't push the popover off-screen.
  const left = Math.max(8, Math.min(x, window.innerWidth - 268))
  const top = Math.max(8, Math.min(y, window.innerHeight - 328))
  return (
    <div className="pop-backdrop" onClick={onClose}>
      <div className="day-pop" style={{ left, top }} onClick={(ev) => ev.stopPropagation()}>
        <div className="day-pop-head">
          {new Date(`${day}T00:00`).toLocaleDateString(undefined,
            { weekday: 'short', month: 'short', day: 'numeric' })}
        </div>
        {events.map((e) => (
          <button key={e.id} className="agenda-ev" style={styleOf(e)} onClick={() => onOpen(e)}>
            <span className="t">
              {e.all_day ? 'all day'
                : e.cont
                  ? (e.end && !e.end_is_date && dayKey(e.end) === day
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
      </div>
    </div>
  )
}

const REPEATS: ReadonlyArray<readonly [string, string]> = [
  ['none', 'Does not repeat'], ['daily', 'Daily'], ['weekly', 'Weekly'],
  ['monthly', 'Monthly'], ['yearly', 'Yearly'],
]

function EventModal({ draft, cals, initialCal, onClose, onSave, onDelete }: {
  draft: Draft; cals: List[]; initialCal: string; onClose: () => void
  onSave: (body: Record<string, unknown>, cal: string, uid?: string) => void
  onDelete: (uid: string, opts?: { recurrence_id?: string | null; scope?: EventScope }) => void
}) {
  const e = draft.event
  const recurring = !!e?.is_recurring
  // Where the event goes: a new event is created here, an existing one is
  // moved here (whole resource — a series always changes calendar as one).
  const [calPick, setCalPick] = useState(initialCal)
  const [summary, setSummary] = useState(e?.summary || '')
  const [allDay, setAllDay] = useState(e ? e.all_day : false)
  const baseDate = draft.date || (e?.start ? dayKey(e.start) : ymd(new Date()))
  const [start, setStart] = useState(
    e?.start ? (e.start.includes('T') ? toLocalInput(e.start) : e.start) : `${baseDate}T09:00`,
  )
  const [end, setEnd] = useState(() => {
    if (!e?.end) return `${baseDate}T10:00`
    if (e.end.includes('T')) return toLocalInput(e.end)
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
  // Snapshot the initial time fields so an "All events" save can tell a real
  // time change (shift the series) from a detail-only edit (leave times alone).
  const [initial] = useState(() => ({ start, end, allDay }))
  const timeChanged = start !== initial.start || end !== initial.end || allDay !== initial.allDay

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
               location, description, tags: tagList(), ...repeatFields() }, calPick)
      return
    }
    const details = { summary, location, description, tags: tagList() }
    if (recurring && scope === 'all') {
      // A changed time plus recurrence_id tells the server to shift the whole
      // series by the same offset (EXDATEs and overrides move along). Untouched
      // times are omitted — resending an occurrence's slot as the master start
      // would slide the series arbitrarily.
      const times = timeChanged
        ? { start: startOut, end: endOut, recurrence_id: e.recurrence_id }
        : {}
      onSave({ ...details, ...times, ...repeatFields(), scope: 'all' }, calPick, e.uid)
    } else if (recurring) {
      onSave({ ...details, start: startOut, end: endOut,
               recurrence_id: e.recurrence_id, scope }, calPick, e.uid)
    } else {
      onSave({ ...details, start: startOut, end: endOut, ...repeatFields() }, calPick, e.uid)
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
            {cals.length > 1 && (
              <div className="field">
                <label className="label">Calendar</label>
                <select className="input" value={calPick} onChange={(ev) => setCalPick(ev.target.value)}>
                  {cals.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
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
                “All events” moves every occurrence by the same offset — use “This event” to move just one.
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

