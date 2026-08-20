import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { api, clientId, type Booking, type BookingLink, type CalEvent, type List, type Task } from '../api'
import { useIsMobile } from '../hooks'
import { useCalendarData, useTaskData, type TaskData } from '../data'
import { cssColor, makeGuard, addDays, dayKey, isOverdue, ymd } from '../util'
import { fmtDue } from '../time'
import { sortTasks, taskKey } from '../order'
import { useTimeFormat } from '../timeformat'
import { bucketByDay, monthGrid, type DayEv } from '../calendar'
import { DayPopover } from './DayPopover'
import {
  COLS, DEFAULT_LAYOUT, GAP, MODULE_KINDS, MODULE_SPECS, ROW_H, addModule, layoutRows,
  moveModule, pxToCellDelta, removeModule, resizeModule, sanitizeLayout,
  type DashboardModule, type ModuleKind,
} from '../dashboard'

// A drag in flight. Kept in a ref (not state) while the pointer moves so the
// grid re-renders off `preview` alone — the raw pixel origin never needs to
// round-trip through React.
interface DragState {
  id: string
  mode: 'move' | 'resize'
  startX: number
  startY: number
  origin: DashboardModule
}

export function HomeView({ rev, onExpire, layout, onLayoutChange,
  hiddenCalendars = [], archivedCalendars = [] }: {
  rev: number
  onExpire: () => void
  layout: DashboardModule[]
  onLayoutChange: (next: DashboardModule[]) => void
  // Read-only here: the mini calendar honours the Calendar tab's visibility
  // choices so an archived calendar doesn't keep dotting the dashboard. That
  // tab stays the sole owner of editing (and pruning) these sets.
  hiddenCalendars?: string[]
  archivedCalendars?: string[]
}) {
  const isMobile = useIsMobile()
  const [arranging, setArranging] = useState(false)
  const [picking, setPicking] = useState(false)
  // The layout as it looks mid-drag. Null when nothing is being dragged, so the
  // committed prop is what renders.
  const [preview, setPreview] = useState<DashboardModule[] | null>(null)
  const drag = useRef<DragState | null>(null)
  const gridRef = useRef<HTMLDivElement>(null)

  // An account that has never arranged anything gets the stock arrangement
  // rather than an empty page. It is not written back until the user actually
  // changes something — an untouched dashboard stays "unset" server-side.
  const committed = layout.length ? layout : DEFAULT_LAYOUT
  const mods = preview ?? committed
  const rows = layoutRows(mods)

  const commit = useCallback((next: DashboardModule[]) => {
    setPreview(null)
    onLayoutChange(sanitizeLayout(next))
  }, [onLayoutChange])

  // ── pointer drag / resize ────────────────────────────────────────────────
  // Pointer Events rather than HTML5 drag-and-drop (which the rest of the app
  // uses for list-to-list drops): a free canvas needs continuous coordinates
  // and a live ghost, and pointer capture gives that without a dependency.
  const onPointerDown = (e: React.PointerEvent, m: DashboardModule, mode: 'move' | 'resize') => {
    if (!arranging) return
    e.preventDefault()
    e.stopPropagation()
    ;(e.target as Element).setPointerCapture(e.pointerId)
    drag.current = { id: m.id, mode, startX: e.clientX, startY: e.clientY, origin: m }
  }

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current
    const width = gridRef.current?.clientWidth ?? 0
    if (!d || !width) return
    const { dx, dy } = pxToCellDelta(e.clientX - d.startX, e.clientY - d.startY, width)
    const next = d.mode === 'move'
      ? moveModule(committed, d.id, d.origin.x + dx, d.origin.y + dy)
      : resizeModule(committed, d.id, d.origin.w + dx, d.origin.h + dy)
    setPreview(next)
  }

  const endDrag = () => {
    if (!drag.current) return
    drag.current = null
    if (preview) commit(preview)
    else setPreview(null)
  }

  // A pointer released outside the grid (or a cancelled gesture) must not leave
  // the layout stuck in preview.
  useEffect(() => {
    if (!arranging) { drag.current = null; setPreview(null) }
  }, [arranging])

  const add = (kind: ModuleKind) => {
    setPicking(false)
    commit(addModule(committed, kind, `m-${clientId().slice(0, 12)}`))
  }

  const placed = useMemo(() => new Set(mods.map((m) => m.kind)), [mods])
  const available = MODULE_KINDS.filter((k) => !placed.has(k))

  // ── data ─────────────────────────────────────────────────────────────────
  // The same lists and tasks the Tasks pane holds — one fetch, not two, and it
  // survives the tab switch that used to send both views back to an empty array.
  const { lists, tasks, loaded, create } = useTaskData()
  // The mini calendar reads the same calendars and window the Calendar tab
  // does, so opening one after the other costs no second fan-out.
  const { cals, eventsFor, requestWindow } = useCalendarData()
  const [links, setLinks] = useState<BookingLink[]>([])
  const [bookings, setBookings] = useState<Booking[]>([])

  const needs = useMemo(() => new Set(mods.map((m) => m.kind)), [mods])
  const needsCal = needs.has('mini_calendar')
  const needsSched = needs.has('booking_links') || needs.has('bookings')

  // The mini calendar's six-week grid. Fetching and rendering share this array,
  // so the days either side of the month can never be dotless for want of data.
  const days = useMemo(() => monthGrid(new Date()), [rev])
  const archived = useMemo(() => new Set(archivedCalendars), [archivedCalendars])
  const hidden = useMemo(() => new Set(hiddenCalendars), [hiddenCalendars])
  const archivedKey = archivedCalendars.join(',')

  // Only ask for what the current arrangement actually shows — a dashboard with
  // no calendar module should not be pulling a month of events, and one with no
  // scheduling module should not be polling the scheduling endpoints.
  const from = ymd(days[0])
  const to = ymd(addDays(days[41], 1))
  // Archived calendars are dropped before the fetch (like the calendar view's
  // `visibleCals`); merely hidden ones are filtered at render, so toggling one
  // never costs a round trip.
  const wanted = useMemo(
    () => (needsCal ? cals.filter((c) => !archived.has(c.id)) : []), [needsCal, cals, archived])
  const events = needsCal ? eventsFor(from, to) : []
  useEffect(() => {
    if (!needsCal) return
    requestWindow(from, to, wanted)
    // eslint-disable-next-line react-hooks/exhaustive-deps
    // `requestWindow` is the missing signal, and it was already here: it is a
    // useCallback over [rev, enabled, fetchWindow], so its identity changes on
    // every SSE bump. Without it in the deps this effect was invariant under
    // `rev` — every other data source on the page consumes it, so the rest of
    // the screen repainted while these events stayed as they were. Adding
    // `rev` directly would work too, but it would be a second source of truth
    // for a signal the callback already carries, and the dep array would still
    // be lying about what the effect reads. Deduping is unaffected:
    // `requestWindow` stamps `asked` with `rev`, so a re-run within one rev is
    // a no-op.
  }, [needsCal, from, to, wanted.map((c) => c.id).join(','), requestWindow])

  // Two sequential requests with no staleness guard: the effect re-runs on
  // `rev`, so two SSE-driven refreshes put two batches in flight and whichever
  // settled last won — painting whatever the older one happened to see. Every
  // other fetch in this app carries this guard (`useTaskData`'s token ref,
  // `fetchWindow`'s per-window generation); this one was the last without it.
  const schedToken = useRef(0)
  useEffect(() => {
    if (!needsSched) { setLinks([]); setBookings([]); return }
    const mine = ++schedToken.current
    const guard = makeGuard(onExpire)
    guard(async () => {
      const ls = await api.schedulingLinks()
      if (mine !== schedToken.current) return
      setLinks(ls)
      const bs = await api.schedulingBookings()
      if (mine !== schedToken.current) return
      setBookings(bs)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rev, needsSched])

  // Through cssColor at the accessor, so every downstream style site is
  // covered: these values are whatever another CalDAV client wrote into the
  // collection's calendar-color, and they land in inline styles — see util.ts.
  const colorOf = useCallback(
    (listId: string) => cssColor(lists.find((l) => l.id === listId)?.color), [lists])

  // An event carries its collection href, not a calendar id — that is what maps
  // it back to the calendar whose color it should wear.
  const calByHref = useMemo(() => new Map(cals.map((c) => [c.href, c] as const)), [cals])
  const eventColor = useCallback(
    (e: CalEvent) => cssColor(calByHref.get(e.calendar)?.color), [calByHref])
  const visibleEvents = useMemo(
    () => events.filter((e) => !hidden.has(calByHref.get(e.calendar)?.id || '')),
    [events, hidden, calByHref])
  const byDay = useMemo(() => bucketByDay(visibleEvents, days), [visibleEvents, days])

  const body = (m: DashboardModule) => (
    <ModuleBody kind={m.kind} tasks={tasks} lists={lists} days={days} byDay={byDay}
      links={links} bookings={bookings} colorOf={colorOf} eventColor={eventColor}
      onExpire={onExpire} loaded={loaded} create={create} />
  )

  // ── mobile: a plain stack ────────────────────────────────────────────────
  // Arranging is desktop-only for now, so phones get the same modules in the
  // saved reading order with none of the drag affordances.
  if (isMobile) {
    const ordered = [...mods].sort((a, b) => (a.y - b.y) || (a.x - b.x))
    return (
      <div className="content">
        <div className="content-head">
          <span className="content-title">Home</span>
          <span className="content-sub">{ordered.length} modules</span>
        </div>
        <div className="scroll dash-stack">
          {ordered.map((m) => (
            <section key={m.id} className="dash-mod">
              <header className="dash-mod-head">
                <span className="label">{MODULE_SPECS[m.kind].label}</span>
              </header>
              <div className="dash-mod-body">{body(m)}</div>
            </section>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="content">
      <div className="content-head">
        <span className="content-title">Home</span>
        <span className="content-sub">
          {arranging ? 'Drag to move · corner to resize' : `${mods.length} modules`}
        </span>
        <span className="spacer" />
        {arranging && (
          <>
            <button className="btn ghost" onClick={() => setPicking((p) => !p)}
              disabled={!available.length} aria-expanded={picking}>
              Add module
            </button>
            <button className="btn ghost" onClick={() => commit(DEFAULT_LAYOUT)}>Reset layout</button>
          </>
        )}
        <button className={`view-tab ${arranging ? 'active' : ''}`} aria-pressed={arranging}
          onClick={() => { setArranging((a) => !a); setPicking(false) }}>
          {arranging ? 'Done' : 'Arrange'}
        </button>
      </div>

      {picking && (
        <div className="dash-picker" role="dialog" aria-label="Add a module">
          {available.map((k) => (
            <button key={k} className="dash-pick" onClick={() => add(k)}>
              <span className="dash-pick-name">{MODULE_SPECS[k].label}</span>
              <span className="dash-pick-blurb">{MODULE_SPECS[k].blurb}</span>
            </button>
          ))}
        </div>
      )}

      <div className="scroll">
        <div ref={gridRef} className={`dash-grid ${arranging ? 'arranging' : ''}`}
          style={{ height: rows * (ROW_H + GAP) }}
          onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={endDrag}>
          {mods.map((m) => (
            // Cells are laid out as percentages of the grid's own width (so the
            // 12 columns stay proportional at any window size), with the gutter
            // subtracted off each module's width/height rather than added
            // between them — that keeps column edges on exact percentages.
            <section key={m.id} className="dash-mod" style={{
              left: `${(m.x / COLS) * 100}%`,
              width: `calc(${(m.w / COLS) * 100}% - ${GAP}px)`,
              top: m.y * (ROW_H + GAP),
              height: m.h * (ROW_H + GAP) - GAP,
            }}>
              <header className="dash-mod-head"
                onPointerDown={(e) => onPointerDown(e, m, 'move')}>
                <span className="label">{MODULE_SPECS[m.kind].label}</span>
                {arranging && (
                  <button className="dash-remove" title="Remove"
                    aria-label={`Remove ${MODULE_SPECS[m.kind].label}`}
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={() => commit(removeModule(committed, m.id))}>✕</button>
                )}
              </header>
              <div className="dash-mod-body">{body(m)}</div>
              {arranging && (
                <span className="dash-grip" aria-hidden="true"
                  onPointerDown={(e) => onPointerDown(e, m, 'resize')} />
              )}
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── module bodies ──────────────────────────────────────────────────────────

function ModuleBody({ kind, tasks, lists, days, byDay, links, bookings, colorOf,
  eventColor, onExpire, loaded, create }: {
  kind: ModuleKind
  tasks: Task[]
  lists: List[]
  days: Date[]
  byDay: Map<string, DayEv[]>
  links: BookingLink[]
  bookings: Booking[]
  colorOf: (listId: string) => string | null
  eventColor: (e: CalEvent) => string | null
  onExpire: () => void
  loaded: boolean
  create: TaskData['create']
}) {
  const today = ymd(new Date())
  // Top-level only, mirroring the Tasks pane — a dashboard card is a summary,
  // and subtasks read as duplicates without their parent for context.
  const tops = tasks.filter((t) => !t.parent)
  const open = tops.filter((t) => !t.completed && !t.cancelled)
  // One order, shared with the Tasks pane (see order.ts). These used to sort by
  // a local comparator that put undated tasks at the opposite end from the one
  // TasksView used, so the same task sat in a different place on each tab.

  switch (kind) {
    case 'today':
      return <TaskList items={sortTasks(open.filter((t) => t.due && dayKey(t.due) === today))}
        colorOf={colorOf} empty="Nothing due today." loaded={loaded} />
    case 'overdue':
      return <TaskList items={sortTasks(open.filter((t) => isOverdue(t.due, t.due_is_date)))}
        colorOf={colorOf} empty="Nothing overdue." overdue loaded={loaded} />
    case 'upcoming': {
      const end = ymd(addDays(new Date(), 7))
      return <TaskList
        items={sortTasks(open
          .filter((t) => t.due && dayKey(t.due) > today && dayKey(t.due) <= end))}
        colorOf={colorOf} empty="Nothing in the next seven days." loaded={loaded} />
    }
    case 'completed': {
      // There is no completion timestamp on the wire, so "recent" is by due date
      // descending — the same proxy the Tasks pane's completed view uses, and
      // like it, undated tasks are appended rather than floated to the top by
      // the reverse.
      const done = tops.filter((t) => t.completed || t.cancelled)
      return <TaskList
        items={[
          ...sortTasks(done.filter((t) => t.due)).reverse(),
          ...sortTasks(done.filter((t) => !t.due)),
        ].slice(0, 40)}
        colorOf={colorOf} empty="Nothing completed yet." done loaded={loaded} />
    }
    case 'mini_calendar':
      return <MiniCalendar days={days} byDay={byDay} eventColor={eventColor} />
    case 'booking_links':
      return <LinkList links={links} />
    case 'bookings':
      return <BookingList bookings={bookings} />
    case 'quick_add':
      return <QuickAddModule lists={lists} create={create} />
    default:
      return null
  }
}

function TaskList({ items, colorOf, empty, overdue, done, loaded }: {
  items: Task[]
  colorOf: (listId: string) => string | null
  empty: string
  overdue?: boolean
  done?: boolean
  loaded?: boolean
}) {
  // Read before the early returns below — a hook can't sit behind a branch.
  const tf = useTimeFormat()
  // Stay blank until the first fetch lands: "Nothing due today." flashing up and
  // then being replaced by a list of tasks reads as a bug. Keyed on `loaded`
  // rather than a `loading` flag that only ever cleared on the success path —
  // one failed request used to leave every module here blank permanently, with
  // no empty state and no error.
  if (!loaded && !items.length) return null
  if (!items.length) return <p className="dash-empty">{empty}</p>
  return (
    <ul className="dash-tasks">
      {items.map((t) => {
        const c = colorOf(t.list)
        return (
          <li key={taskKey(t)} className={`dash-task ${done ? 'done' : ''}`}>
            <span className="list-dot" style={c ? { background: c } : undefined} />
            <span className="dash-task-title">{t.summary || '(untitled)'}</span>
            {t.due && (
              <span className={`dash-task-due mono ${overdue ? 'overdue' : ''}`}>
                {fmtDue(t.due, t.due_is_date, tf)}
              </span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

// At most this many dots fit under a day number without crowding it.
const MAX_DOTS = 3

/** The distinct calendar colors on a day, in the order its events start.
 *
 * Deduped by color rather than by event: five standups on one calendar are one
 * dot, so the strip reads as "which calendars", not "how many meetings". */
function dotColors(evs: DayEv[], eventColor: (e: CalEvent) => string | null): (string | null)[] {
  const seen = new Set<string | null>()
  const out: (string | null)[] = []
  for (const e of evs) {
    const c = eventColor(e)
    if (seen.has(c)) continue
    seen.add(c)
    out.push(c)
    if (out.length === MAX_DOTS) break
  }
  return out
}

function MiniCalendar({ days, byDay, eventColor }: {
  days: Date[]
  byDay: Map<string, DayEv[]>
  eventColor: (e: CalEvent) => string | null
}) {
  const now = new Date()
  const today = ymd(now)
  // The grid is always the current month, so the middle of it names the month
  // the cells outside get dimmed against.
  const month = days.length ? days[Math.floor(days.length / 2)].getMonth() : now.getMonth()
  const [open, setOpen] = useState<{ day: string; x: number; y: number } | null>(null)
  // The day that opened the popover, so focus lands back on it when it closes.
  const anchor = useRef<HTMLButtonElement | null>(null)

  const close = useCallback(() => {
    setOpen(null)
    anchor.current?.focus()
  }, [])

  return (
    <div className="mini-cal">
      <div className="mini-cal-head">
        {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((d, i) => (
          <span key={i} className="label">{d}</span>
        ))}
      </div>
      <div className="mini-cal-grid">
        {days.map((d) => {
          const key = ymd(d)
          const evs = byDay.get(key) ?? []
          const cls = [
            'mini-day',
            d.getMonth() === month ? '' : 'dim',
            key === today ? 'today' : '',
            evs.length ? 'busy' : '',
          ].filter(Boolean).join(' ')
          const long = d.toLocaleDateString(undefined,
            { weekday: 'long', month: 'long', day: 'numeric' })
          return (
            <button key={key} type="button" className={cls}
              // A quiet day has nothing to show, and leaving all 42 cells
              // focusable would bury the rest of the dashboard behind them.
              disabled={!evs.length}
              aria-label={evs.length
                ? `${long}, ${evs.length} event${evs.length === 1 ? '' : 's'}`
                : long}
              aria-haspopup="dialog"
              aria-expanded={open?.day === key}
              onClick={(e) => {
                const r = e.currentTarget.getBoundingClientRect()
                anchor.current = e.currentTarget
                // Below the cell, not level with it: a day number is too short
                // to hang a popover off its top edge without covering the grid.
                setOpen({ day: key, x: r.left, y: r.bottom + 4 })
              }}>
              {d.getDate()}
              {evs.length > 0 && (
                <span className="mini-dots" aria-hidden="true">
                  {dotColors(evs, eventColor).map((c, i) => (
                    <i key={i} className="mini-dot"
                      style={c ? { '--ev-c': c } as CSSProperties : undefined} />
                  ))}
                </span>
              )}
            </button>
          )
        })}
      </div>
      {open && (
        // No `onOpen`: the dashboard shows the day, the Calendar tab edits it.
        <DayPopover day={open.day} x={open.x} y={open.y} events={byDay.get(open.day) ?? []}
          styleOf={(e) => {
            const c = eventColor(e)
            return c ? { '--ev-c': c } as CSSProperties : undefined
          }}
          onClose={close} />
      )}
    </div>
  )
}

function LinkList({ links }: { links: BookingLink[] }) {
  if (!links.length) return <p className="dash-empty">No booking links yet.</p>
  return (
    <ul className="dash-tasks">
      {links.map((l) => (
        <li key={l.token} className={`dash-task ${l.enabled ? '' : 'done'}`}>
          <span className="dash-task-title">{l.title}</span>
          <span className="dash-task-due mono">{l.duration_minutes}m</span>
        </li>
      ))}
    </ul>
  )
}

function BookingList({ bookings }: { bookings: Booking[] }) {
  const tf = useTimeFormat()
  const upcoming = bookings
    .filter((b) => new Date(b.start).getTime() >= Date.now())
    .sort((a, b) => a.start.localeCompare(b.start))
    .slice(0, 20)
  if (!upcoming.length) return <p className="dash-empty">No upcoming bookings.</p>
  return (
    <ul className="dash-tasks">
      {upcoming.map((b) => (
        <li key={b.id} className="dash-task">
          <span className="dash-task-title">{b.name}</span>
          <span className="dash-task-due mono">{fmtDue(b.start, false, tf)}</span>
        </li>
      ))}
    </ul>
  )
}

function QuickAddModule({ lists, create }: { lists: List[]; create: TaskData['create'] }) {
  const [text, setText] = useState('')
  const [listId, setListId] = useState('')
  // What the last submit did, cleared on the next keystroke. A task added here
  // lands on a list, but every task module on this dashboard filters by due
  // date or completion — so an undated one appears in none of them, and without
  // a word the form looks like it swallowed the entry. Confirming beats an
  // optimistic paint on a card that would not have shown it either way.
  const [added, setAdded] = useState<string | null>(null)
  const target = listId || lists[0]?.id || ''

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const summary = text.trim()
    if (!summary || !target) return
    setText('')
    setAdded(null)
    const t = await create(target, { summary })
    // Put the text back rather than losing it: a failed add used to be
    // indistinguishable from a successful one apart from a toast.
    if (!t) { setText(summary); return }
    setAdded(lists.find((l) => l.id === target)?.name ?? null)
  }

  if (!lists.length) return <p className="dash-empty">Create a list first.</p>
  return (
    <form className="dash-quickadd" onSubmit={submit}>
      <input className="input" value={text}
        onChange={(e) => { setText(e.target.value); setAdded(null) }}
        placeholder="Add a task…" aria-label="Add a task" />
      <select className="input quickadd-list" value={target}
        onChange={(e) => setListId(e.target.value)} aria-label="List">
        {lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
      </select>
      <button className="btn" type="submit" disabled={!text.trim()}>Add</button>
      {added && <p className="dash-added" role="status">Added to {added}.</p>}
    </form>
  )
}
