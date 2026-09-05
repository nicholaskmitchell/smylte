import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import {
  api, clientId,
  type Booking, type BookingLink, type CalEvent, type DayEntry, type DayPlan,
  type List, type Task,
} from '../api'
import { useIsMobile, useToday } from '../hooks'
import { useCalendarData, useTaskData, type TaskData } from '../data'
import { cssColor, makeGuard, addDays, dayKey, isOverdue, textDir, ymd } from '../util'
import { fmtDue, fmtDuration } from '../time'
import { sortByCompletion, sortTasks, taskKey } from '../order'
import { useTimeFormat } from '../timeformat'
import { bucketByDay, monthGrid, type DayEv } from '../calendar'
import { DayPopover } from './DayPopover'
import { entryTitle, orderEntries, rowDone } from './TodayView'
import { readCachedDayPlan } from '../cache'
import { useI18n, useT } from '../i18n'
import { weekdayNames } from '../names'
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
  /** The owner's arrangement, or NULL when they have never made one. The two
   *  are different: `null` takes the stock five, `[]` is a board deliberately
   *  cleared. Collapsing them meant removing the last module put five back. */
  layout: DashboardModule[] | null
  onLayoutChange: (next: DashboardModule[]) => void
  // Read-only here: the mini calendar honours the Calendar tab's visibility
  // choices so an archived calendar doesn't keep dotting the dashboard. That
  // tab stays the sole owner of editing (and pruning) these sets.
  hiddenCalendars?: string[]
  archivedCalendars?: string[]
}) {
  const tr = useT()
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
  //
  // Keyed on NULL, not on emptiness. `layout.length ? … : DEFAULT_LAYOUT` made
  // "never arranged" and "deliberately empty" the same board, so removing the
  // last module handed back the stock five — a Remove that ADDS five modules,
  // and no way to reach an empty dashboard at all.
  const committed = layout ?? DEFAULT_LAYOUT
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

  // A RELEASE commits. `pointerup` is the gesture finishing where the user let
  // go, and only that is an instruction.
  const endDrag = () => {
    if (!drag.current) return
    drag.current = null
    if (preview) commit(preview)
    else setPreview(null)
  }

  // A CANCEL discards. `pointercancel` means the platform took the gesture over
  // — the finger never came up, so there is no position the user chose. Sharing
  // `endDrag` between the two wrote the module to wherever the pointer happened
  // to be when the browser started panning, and `commit` calls `onLayoutChange`,
  // which App persists with `saveSettingsSoon({dashboard})`. That is not a
  // stray preview to be cleaned up later: it is a saved arrangement nobody made.
  //
  // Not theoretical. Arrange mode is gated on `useIsMobile` (max-width 720px),
  // so every touch device WIDER than that gets it — an iPad in landscape, a
  // Surface, a touchscreen laptop — and there the browser steals a downward drag
  // to scroll the enclosing `.scroll`, firing pointercancel every time. The
  // `touch-action: none` now on the handles (app.css) is the other half: it
  // stops the steal happening, and this stops the theft being recorded as a move.
  const cancelDrag = () => {
    if (!drag.current) return
    drag.current = null
    setPreview(null)
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
  const {
    lists, tasks, loaded, create, toggle, taskListErrors, taskListsFailed, reloadTasks,
  } = useTaskData()
  // The mini calendar reads the same calendars and window the Calendar tab
  // does, so opening one after the other costs no second fan-out.
  const { cals, eventsFor, requestWindow, windowErrors } = useCalendarData()
  const [links, setLinks] = useState<BookingLink[]>([])
  const [bookings, setBookings] = useState<Booking[]>([])

  const needs = useMemo(() => new Set(mods.map((m) => m.kind)), [mods])
  const needsCal = needs.has('mini_calendar')
  const needsSched = needs.has('booking_links') || needs.has('bookings')
  const needsPlan = needs.has('day_plan')

  // ── the day's plan ───────────────────────────────────────────────────────
  //
  // A READ, and only ever a read. `api.openDay` is the one call that can CREATE
  // a plan — it derives a snapshot from CalDAV and writes it — and the Today tab
  // is built around being the only caller. A dashboard that opened the day would
  // snapshot it on a morning the owner never looked at it, which is not a thing
  // a dashboard gets to decide. On a day nobody has opened this answers
  // `planned: false` with no rows, and the module says so rather than inventing
  // any.
  //
  // Seeded from the disk mirror the Today tab already writes, so the card paints
  // on the first frame instead of after the slowest read the app makes.
  const todayKey = useToday()
  const [plan, setPlan] = useState<DayPlan | null>(() => readCachedDayPlan(ymd(new Date())))
  // The same staleness guard `needsSched` carries below and for the same reason:
  // the effect re-runs on `rev`, so two SSE-driven refreshes put two reads in
  // flight and whichever settled last would win.
  const planToken = useRef(0)
  useEffect(() => {
    if (!needsPlan) return
    const mine = ++planToken.current
    const guard = makeGuard(onExpire)
    guard(async () => {
      const p = await api.day(todayKey)
      if (mine === planToken.current) setPlan(p)
    })
  }, [rev, needsPlan, todayKey, onExpire])
  // A day the picker never wrote — or a rollover — leaves a plan for the wrong
  // day in hand. Gated rather than filtered: rows from yesterday under a heading
  // that says today is the one mistake a day-scoped surface cannot make.
  const planForToday = plan && plan.day === todayKey ? plan : null

  // The mini calendar's six-week grid. Fetching and rendering share this array,
  // so the days either side of the month can never be dotless for want of data.
  // Keyed on the day as well as on `rev`: `rev` moves only when the server
  // publishes a change, so a dashboard left open across a month boundary on a
  // quiet account kept last month's grid — `useToday` re-rendered it at
  // midnight, but a re-render does not recompute a memo whose deps stood still,
  // and the fetch window below is cut from this same array.
  const days = useMemo(() => monthGrid(new Date()), [rev, todayKey])
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
  // The mini calendar has to report a failed calendar for itself. `fetchWindow`
  // uses `allSettled`, so an ordinary 502 never reaches `makeGuard`'s catch and
  // the error toast that used to cover this page is gone. `CalendarView` grew a
  // banner in its place; this module reads the same signal, or a dashboard
  // would show a month quietly short of events with nothing to say so.
  const calErrors = needsCal ? windowErrors(from, to) : []
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
  // Whether the last batch FAILED. `makeGuard` swallows a 502, a 429 or a
  // timeout into a toast and resolves undefined, so neither setter above ran
  // and the two modules printed "No booking links yet." / "No upcoming
  // bookings." over an account with live links — the confident lie the
  // Scheduling tab's `failed` flag exists to stop, and the mini calendar next
  // to them reports through `home.calPartial`. Same rule, same shape.
  const [schedFailed, setSchedFailed] = useState(false)
  useEffect(() => {
    if (!needsSched) { setLinks([]); setBookings([]); setSchedFailed(false); return }
    const mine = ++schedToken.current
    const guard = makeGuard(onExpire)
    guard(async () => {
      const ls = await api.schedulingLinks()
      if (mine !== schedToken.current) return
      setLinks(ls)
      const bs = await api.schedulingBookings()
      if (mine !== schedToken.current) return
      setBookings(bs)
      return true
    }).then((ok) => { if (mine === schedToken.current) setSchedFailed(!ok) })
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
      calErrors={calErrors} taskErrors={taskListErrors} failedLists={taskListsFailed}
      reloadTasks={reloadTasks}
      links={links} bookings={bookings} schedFailed={schedFailed}
      colorOf={colorOf} eventColor={eventColor}
      onExpire={onExpire} loaded={loaded} create={create}
      plan={planForToday} onPlan={setPlan} toggleTask={toggle} tasksLoaded={loaded} />
  )

  // ── mobile: a plain stack ────────────────────────────────────────────────
  // Arranging is desktop-only for now, so phones get the same modules in the
  // saved reading order with none of the drag affordances.
  if (isMobile) {
    const ordered = [...mods].sort((a, b) => (a.y - b.y) || (a.x - b.x))
    return (
      <div className="content">
        <div className="content-head">
          <span className="content-title">{tr('home.title')}</span>
          <span className="content-sub">
            {tr('home.moduleCount', { count: ordered.length })}
          </span>
        </div>
        <div className="scroll dash-stack">
          {ordered.map((m) => (
            <section key={m.id} className="dash-mod">
              <header className="dash-mod-head">
                <span className="label">{tr(MODULE_SPECS[m.kind].label)}</span>
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
        <span className="content-title">{tr('home.title')}</span>
        <span className="content-sub">
          {arranging
            ? tr('home.arrangeHint')
            : tr('home.moduleCount', { count: mods.length })}
        </span>
        <span className="spacer" />
        {arranging && (
          <>
            <button className="btn ghost" onClick={() => setPicking((p) => !p)}
              disabled={!available.length} aria-expanded={picking}>
              {tr('home.addModule')}
            </button>
            <button className="btn ghost" onClick={() => commit(DEFAULT_LAYOUT)}>
              {tr('home.resetLayout')}
            </button>
          </>
        )}
        <button className={`view-tab ${arranging ? 'active' : ''}`} aria-pressed={arranging}
          onClick={() => { setArranging((a) => !a); setPicking(false) }}>
          {arranging ? tr('home.arrangeDone') : tr('home.arrange')}
        </button>
      </div>

      {picking && (
        <div className="dash-picker" role="dialog" aria-label={tr('home.picker')}>
          {available.map((k) => (
            <button key={k} className="dash-pick" onClick={() => add(k)}>
              <span className="dash-pick-name">{tr(MODULE_SPECS[k].label)}</span>
              <span className="dash-pick-blurb">{tr(MODULE_SPECS[k].blurb)}</span>
            </button>
          ))}
        </div>
      )}

      <div className="scroll">
        <div ref={gridRef} className={`dash-grid ${arranging ? 'arranging' : ''}`}
          style={{ height: rows * (ROW_H + GAP) }}
          onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={cancelDrag}>
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
                <span className="label">{tr(MODULE_SPECS[m.kind].label)}</span>
                {arranging && (
                  <button className="dash-remove" title={tr('common.remove')}
                    aria-label={tr('home.removeModule',
                      { module: tr(MODULE_SPECS[m.kind].label) })}
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

function ModuleBody({ kind, tasks, lists, days, byDay, calErrors, taskErrors, failedLists,
  reloadTasks, links, bookings, schedFailed, colorOf, eventColor, onExpire, loaded, create,
  plan, onPlan, toggleTask, tasksLoaded }: {
  kind: ModuleKind
  tasks: Task[]
  lists: List[]
  days: Date[]
  byDay: Map<string, DayEv[]>
  /** Calendars whose fetch failed for this window, by name. */
  calErrors: string[]
  /** Task lists whose fetch failed, by name — and by id, for the plan rows. */
  taskErrors: string[]
  failedLists: string[]
  reloadTasks: () => void
  links: BookingLink[]
  bookings: Booking[]
  /** The scheduling batch failed: neither list is evidence about the account. */
  schedFailed: boolean
  colorOf: (listId: string) => string | null
  eventColor: (e: CalEvent) => string | null
  onExpire: () => void
  loaded: boolean
  create: TaskData['create']
  /** Today's plan, or null while it is unknown. Already checked to be TODAY's
   *  by the caller. */
  plan: DayPlan | null
  onPlan: (next: DayPlan | null | ((p: DayPlan | null) => DayPlan | null)) => void
  toggleTask: TaskData['toggle']
  tasksLoaded: boolean
}) {
  const tr = useT()
  const today = ymd(new Date())
  // Top-level only, mirroring the Tasks pane — a dashboard card is a summary,
  // and subtasks read as duplicates without their parent for context.
  const tops = tasks.filter((t) => !t.parent)
  const open = tops.filter((t) => !t.completed && !t.cancelled)
  // One order, shared with the Tasks pane (see order.ts). These used to sort by
  // a local comparator that put undated tasks at the opposite end from the one
  // TasksView used, so the same task sat in a different place on each tab.

  // The task modules all read the one array, so they are all short by the
  // same lists when one fails; each says so rather than printing an empty
  // state over a fetch that did not land.
  const partial = taskErrors.length > 0
    ? <TasksPartial lists={taskErrors} onRetry={reloadTasks} /> : null

  switch (kind) {
    case 'today':
      return <TaskList items={sortTasks(open.filter((t) => t.due && dayKey(t.due) === today))}
        colorOf={colorOf} empty={tr('home.emptyToday')} loaded={loaded} partial={partial} />
    case 'overdue':
      return <TaskList items={sortTasks(open.filter((t) => isOverdue(t.due, t.due_is_date)))}
        colorOf={colorOf} empty={tr('home.emptyOverdue')} overdue loaded={loaded}
        partial={partial} />
    case 'upcoming': {
      const end = ymd(addDays(new Date(), 7))
      return <TaskList
        items={sortTasks(open
          .filter((t) => t.due && dayKey(t.due) > today && dayKey(t.due) <= end))}
        colorOf={colorOf} empty={tr('home.emptyUpcoming')} loaded={loaded} partial={partial} />
    }
    case 'completed': {
      // Most recently finished first, by the COMPLETED stamp the wire has always
      // carried. This module used to sort by due date descending under a comment
      // asserting no such stamp existed; it did, and `_task_dto` simply never
      // sent it. `sortByCompletion` is shared with the Tasks pane's completed
      // view, which had the same block written out a second time.
      const done = tops.filter((t) => t.completed || t.cancelled)
      return <TaskList items={sortByCompletion(done).slice(0, 40)}
        colorOf={colorOf} empty={tr('home.emptyCompleted')} done loaded={loaded}
        partial={partial} />
    }
    case 'day_plan':
      return <DayPlanList plan={plan} tasks={tasks} tasksLoaded={tasksLoaded}
        failedLists={failedLists} partial={partial}
        colorOf={colorOf} onExpire={onExpire} onPlan={onPlan} toggleTask={toggleTask} />
    case 'mini_calendar':
      return <MiniCalendar days={days} byDay={byDay} eventColor={eventColor} failed={calErrors} />
    case 'booking_links':
      return <LinkList links={links} failed={schedFailed} />
    case 'bookings':
      return <BookingList bookings={bookings} failed={schedFailed} />
    case 'quick_add':
      return <QuickAddModule lists={lists} create={create} />
    default:
      return null
  }
}

/** The `.cal-partial` banner TasksView renders, for a card: which lists are
 *  missing, and the retry the data layer offers. */
function TasksPartial({ lists, onRetry }: { lists: string[]; onRetry: () => void }) {
  const tr = useT()
  return (
    <div className="cal-partial" role="status">
      {tr('tasks.partial', { lists: lists.join(', ') })}{' '}
      <button type="button" className="btn ghost" onClick={onRetry}>{tr('common.retry')}</button>
    </div>
  )
}

function TaskList({ items, colorOf, empty, overdue, done, loaded, partial }: {
  items: Task[]
  colorOf: (listId: string) => string | null
  empty: string
  overdue?: boolean
  done?: boolean
  loaded?: boolean
  /** The short-pane banner, when a list failed; null otherwise. */
  partial?: React.ReactNode
}) {
  const tr = useT()
  const { locale } = useI18n()
  // Read before the early returns below — a hook can't sit behind a branch.
  const tf = useTimeFormat()
  // Stay blank until the first fetch lands: "Nothing due today." flashing up and
  // then being replaced by a list of tasks reads as a bug. Keyed on `loaded`
  // rather than a `loading` flag that only ever cleared on the success path —
  // one failed request used to leave every module here blank permanently, with
  // no empty state and no error.
  if (!loaded && !items.length) return null
  // A list that failed is not an absence: the banner stands in for the empty
  // copy, which would otherwise be a confident statement about rows this
  // module never received.
  if (!items.length) return partial ?? <p className="dash-empty">{empty}</p>
  return (
    <>
    {partial}
    <ul className="dash-tasks">
      {items.map((t) => {
        const c = colorOf(t.list)
        return (
          <li key={taskKey(t)} className={`dash-task ${done ? 'done' : ''}`}>
            <span className="list-dot" style={c ? { background: c } : undefined} />
            <span className="dash-task-title">{t.summary || tr('common.untitled')}</span>
            {t.due && (
              <span className={`dash-task-due mono ${overdue ? 'overdue' : ''}`}>
                {fmtDue(t.due, t.due_is_date, tf, locale)}
              </span>
            )}
          </li>
        )
      })}
    </ul>
    </>
  )
}

/**
 * Today's plan, as the dashboard shows it: the same rows the Today tab has, in
 * the same order, tickable.
 *
 * NOT a second implementation of that tab. `orderEntries`, `entryTitle` and
 * `rowDone` all come from it, because those three are where two surfaces would
 * quietly come to disagree about one row — which order it sits in, what it is
 * called once its task has been deleted, and whether it counts as done. What is
 * NOT borrowed is `TodayRow` itself: drag handles, an editable estimate, a drop
 * button and a weekly habit count are the tab's business, and a summary card
 * that grew them would be the tab in a smaller box.
 *
 * `rowDone(…, true)` — live — because a dashboard only ever shows today, so a
 * task row reads its doneness off the task NOW rather than off a completion
 * stamp that has to fall on the right day.
 */
function DayPlanList({ plan, tasks, tasksLoaded, failedLists, partial, colorOf, onExpire, onPlan,
  toggleTask }: {
  plan: DayPlan | null
  tasks: Task[]
  tasksLoaded: boolean
  /** Ids of the lists whose fetch failed: a task row from one is unknown, not
   *  gone — the same distinction `focus.ts` draws for the Focus queue. */
  failedLists: string[]
  partial?: React.ReactNode
  colorOf: (listId: string) => string | null
  onExpire: () => void
  onPlan: (next: DayPlan | null | ((p: DayPlan | null) => DayPlan | null)) => void
  toggleTask: TaskData['toggle']
}) {
  const tr = useT()
  // A task entry joins back to its task on (list, uid) — never on uid alone. A
  // CalDAV UID is unique per COLLECTION, so the same one can live in two lists.
  const taskFor = useMemo(() => {
    const by = new Map(tasks.map((t) => [taskKey(t), t] as const))
    return (e: DayEntry) => (e.kind === 'task' && e.list && e.uid
      ? by.get(`${e.list}\u0000${e.uid}`) : undefined)
  }, [tasks])

  /** Tick a row whose doneness lives ON THE ENTRY: a note, or a habit
   *  occurrence. A task row never reaches this — the task's own state is the
   *  truth, and `toggleTask` is what writes it. */
  const toggleEntry = async (e: DayEntry) => {
    if (!plan) return
    const done = !e.done_at
    const at = done ? new Date().toISOString() : null
    const patch = (stamp: string | null) => onPlan((p) => (p && p.day === plan.day
      ? { ...p, entries: p.entries.map((x) => (x.entry_id === e.entry_id
        ? { ...x, done_at: stamp } : x)) }
      : p))
    // Painted first, settled second, and put back on failure — `guard` has
    // already raised the toast. THE STAMP ONLY on every arm: `patchDayEntry`
    // answers with the whole row, and settling all of it would give this reply
    // an opinion about an estimate somebody typed on the Today tab a moment ago.
    patch(at)
    const dto = await makeGuard(onExpire)(() =>
      api.patchDayEntry(plan.day, e.entry_id, { done }))
    patch(dto ? dto.done_at : e.done_at)
  }

  // Nothing to say yet. Blank rather than "Nothing on today" — the empty state
  // flashing up before the rows land reads as a bug, which is the same call
  // `TaskList` makes one function up.
  if (!plan) return null
  // Dropped rows are decisions, not work: "I am not doing this" belongs in the
  // day's own record and not on a card that answers "what am I doing".
  const rows = orderEntries(plan.entries.filter((e) => !e.dropped_at))
  if (!rows.length) return <p className="dash-empty">{tr('home.planEmpty')}</p>
  return (
    <>
    {partial}
    <ul className="dash-tasks">
      {rows.map((e) => {
        const task = taskFor(e)
        const done = rowDone(e, task, true)
        // A task row whose LIST failed to load is not "no longer in your
        // lists" — the server still names it; this client could not read it.
        // Its title says that instead, and its tick is disabled for the same
        // reason an orphan's is: there is no task here to write to.
        const unavailable = e.kind === 'task' && !task && failedLists.includes(e.list ?? '')
        const title = unavailable ? tr('today.taskUnavailable') : entryTitle(e, task, tasksLoaded, tr)
        // A task entry whose task is gone can still be read, but not ticked:
        // there is nothing left to tick. Disabled rather than absent, so the
        // row keeps the column every other row has.
        const orphan = e.kind === 'task' && !task
        return (
          <li key={e.entry_id} className={`dash-task dash-day-row ${done ? 'done' : ''}`}>
            <button type="button" className={`check ${done ? 'on' : ''}`}
              disabled={orphan}
              aria-pressed={done}
              aria-label={done
                ? tr('home.planUncheck', { entry: title || tr('today.entry') })
                : tr('home.planCheck', { entry: title || tr('today.entry') })}
              onClick={() => void (task ? toggleTask(task) : orphan ? null : toggleEntry(e))}>
              ✓
            </button>
            {/* The Today tab's own three-way mark, class for class. It is
                self-contained (`--today-mark-w` is on `:root`) and it is the
                vocabulary that tab teaches: filled is a task and leaves the
                app, hollow is a note and does not, ↻ is a habit. Teaching it
                there and dropping it here would undo the teaching. */}
            <span className="today-kind-mark" data-kind={e.kind} role="img"
              aria-label={tr(KIND_ARIA[e.kind] ?? 'today.kind.entry')}>
              {e.kind === 'habit'
                ? <span aria-hidden="true">↻</span>
                : <span className="today-kind-box" style={e.kind === 'task' && colorOf(e.list ?? '')
                  ? { background: colorOf(e.list ?? '')! } : undefined} />}
            </span>
            <span className="dash-task-title" dir={textDir(title)}>{title}</span>
            <PlanRowMeta entry={e} task={task} />
          </li>
        )
      })}
    </ul>
    </>
  )
}

/** A day entry's `kind` → the name assistive tech gets for its mark. The Today
 *  tab's `KIND_LABEL` keyed the same way and read with the same fallback, and
 *  for the reason api.ts gives: `DayEntryKind` widens silently, so a kind this
 *  build has not heard of announces itself as "Entry" rather than handing a
 *  screen reader a nameless `role="img"`. */
const KIND_ARIA: Record<string, string> = {
  task: 'today.kind.task', note: 'today.kind.note', habit: 'today.kind.habit',
}

/** The one thing on the right of a plan row.
 *
 *  The Today tab has room for an estimate AND a due date in separate columns;
 *  a dashboard card has room for one, so this picks the one that says
 *  something. The estimate wins when there is one — "what am I doing today" is
 *  a question about time. Failing that, a due date, but only when it is NOT
 *  today: a due of today repeated down every row of a card headed "Today's
 *  plan" is the date already in the heading, said again per row. */
function PlanRowMeta({ entry, task }: { entry: DayEntry; task: Task | undefined }) {
  const { locale } = useI18n()
  const tf = useTimeFormat()
  if (entry.estimate_minutes != null) {
    return <span className="dash-task-due mono">{fmtDuration(entry.estimate_minutes)}</span>
  }
  if (!task?.due || dayKey(task.due) === entry.day) return null
  return (
    <span className={`dash-task-due mono ${isOverdue(task.due, task.due_is_date) ? 'overdue' : ''}`}>
      {fmtDue(task.due, task.due_is_date, tf, locale)}
    </span>
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

function MiniCalendar({ days, byDay, eventColor, failed = [] }: {
  failed?: string[]
  days: Date[]
  byDay: Map<string, DayEv[]>
  eventColor: (e: CalEvent) => string | null
}) {
  const tr = useT()
  const { locale } = useI18n()
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
      {failed.length > 0 && (
        <div className="cal-partial" role="status">
          {tr('home.calPartial', { cals: failed.join(', ') })}
        </div>
      )}
      <div className="mini-cal-head">
        {/* Sunday-first: the grid below is built from real dates and its
            columns line up by `Date#getDay`. Narrow, because a mini-calendar
            column is one character wide — and from `Intl`, so the character is
            the one that language uses. */}
        {weekdayNames(locale, 'narrow', 'sun').map((d, i) => (
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
          const long = d.toLocaleDateString(locale,
            { weekday: 'long', month: 'long', day: 'numeric' })
          return (
            <button key={key} type="button" className={cls}
              // A quiet day has nothing to show, and leaving all 42 cells
              // focusable would bury the rest of the dashboard behind them.
              disabled={!evs.length}
              aria-label={evs.length
                ? tr('home.dayWithEvents', { day: long, count: evs.length })
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

function LinkList({ links, failed }: { links: BookingLink[]; failed: boolean }) {
  const tr = useT()
  // Never the empty copy over a failed fetch — see `schedFailed`.
  if (failed) return <p className="dash-empty" role="status">{tr('home.linksFailed')}</p>
  if (!links.length) return <p className="dash-empty">{tr('home.noLinks')}</p>
  return (
    <ul className="dash-tasks">
      {links.map((l) => (
        <li key={l.token} className={`dash-task ${l.enabled ? '' : 'done'}`}>
          <span className="dash-task-title">{l.title}</span>
          <span className="dash-task-due mono">
            {tr('home.linkDuration', { n: l.duration_minutes })}
          </span>
        </li>
      ))}
    </ul>
  )
}

function BookingList({ bookings, failed }: { bookings: Booking[]; failed: boolean }) {
  const tr = useT()
  const { locale } = useI18n()
  const tf = useTimeFormat()
  // Ordered by the INSTANT, not the string: `start` carries each link's own
  // offset, so with links in two zones the text order is not the clock order
  // — "09:00-07:00" sorts before "10:00+02:00" and lists nine hours later.
  // The server's list_bookings sorts the same way (finding of the same sweep).
  const upcoming = bookings
    .filter((b) => new Date(b.start).getTime() >= Date.now())
    .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime())
    .slice(0, 20)
  if (failed) return <p className="dash-empty" role="status">{tr('home.bookingsFailed')}</p>
  if (!upcoming.length) return <p className="dash-empty">{tr('home.noBookings')}</p>
  return (
    <ul className="dash-tasks">
      {upcoming.map((b) => (
        <li key={b.id} className="dash-task">
          <span className="dash-task-title">{b.name}</span>
          <span className="dash-task-due mono">{fmtDue(b.start, false, tf, locale)}</span>
        </li>
      ))}
    </ul>
  )
}

function QuickAddModule({ lists, create }: { lists: List[]; create: TaskData['create'] }) {
  const tr = useT()
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

  if (!lists.length) return <p className="dash-empty">{tr('home.needList')}</p>
  return (
    <form className="dash-quickadd" onSubmit={submit}>
      <input className="input" value={text}
        onChange={(e) => { setText(e.target.value); setAdded(null) }}
        placeholder={tr('home.quickAddPlaceholder')} aria-label={tr('home.quickAddAria')} />
      <select className="input quickadd-list" value={target}
        onChange={(e) => setListId(e.target.value)} aria-label={tr('field.list')}>
        {lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
      </select>
      <button className="btn" type="submit" disabled={!text.trim()}>{tr('common.add')}</button>
      {added && (
        <p className="dash-added" role="status">{tr('home.addedTo', { list: added })}</p>
      )}
    </form>
  )
}
