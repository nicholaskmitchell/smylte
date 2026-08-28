import {
  useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties,
} from 'react'
import {
  api, clientId, uidFor, type CalEvent, type EventScope, type List, type Task,
} from '../api'
import { useCalendarData, useTaskData } from '../data'
import { useEscape } from '../hooks'
import { cssColor, dayKey, makeGuard, pad, sameValue, textDir, toLocalInput, ymd } from '../util'
import { fmtClock, inputLang } from '../time'
import { useTimeFormat } from '../timeformat'
import {
  bucketByDay, bucketTasksByDay, cellCapacity, chipsShown, dragBody, daysBetween,
  endFromDuration, eventKey, lastDayOf, monthGrid, shiftYmd, type CalendarFit, type DayEv,
} from '../calendar'
import { TagInput } from './AddMultipleModal'
import { taskKey } from '../order'
import { useIsMobile } from '../hooks'
import { AgendaEvent, AgendaTask, DayPopover } from './DayPopover'
import { Sidebar } from './Sidebar'
import { TaskModal } from './TaskModal'
import { DateTimeInput } from './DateTimeInput'

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December']

interface Draft { event?: CalEvent; date?: string }

// How many chips a desktop day cell shows before collapsing the rest into
// "+N more". Counted over events and tasks together, so the number is the
// whole remainder rather than one kind's share of it.
//
// The cap for a dynamic grid, where the cell grows to fit whatever it is given.
// A fixed grid measures its own instead (see `measureCells`) and falls back to
// this until it can.
const CELL_MAX = 4

/**
 * How many chips a cell of the currently rendered grid can hold, or null while
 * nothing is measurable.
 *
 * Read off the DOM rather than derived from the stylesheet: a fixed cell's
 * height comes from the pane it is stretched into, and a chip's from
 * `--fs-scale` and whichever font the account chose — neither is knowable here.
 * `.cal-ev, .cal-task` is looked up across the whole grid, not inside one cell,
 * because most cells hold no chip to measure; every chip is the same height, so
 * any of them answers for all.
 */
function measureCells(root: HTMLElement | null): number | null {
  const cell = root?.querySelector('.cal-cell') as HTMLElement | null
  const head = cell?.querySelector('.daynum') as HTMLElement | null
  const chip = root?.querySelector('.cal-ev, .cal-task') as HTMLElement | null
  if (!cell || !head || !chip) return null
  const cs = getComputedStyle(cell)
  return cellCapacity({
    // clientHeight is the padding box, so the cell's own padding comes off it.
    inner: cell.clientHeight - (parseFloat(cs.paddingTop) || 0) - (parseFloat(cs.paddingBottom) || 0),
    head: head.getBoundingClientRect().height,
    chip: chip.getBoundingClientRect().height,
    gap: parseFloat(cs.rowGap) || 0,
  })
}

/**
 * The local stand-in for an event whose create is still in flight, carrying the
 * uid the server will derive from the same client_id (see `uidFor`).
 *
 * `calendar` is the collection *href*, not the calendar id: `calByHref` is what
 * maps an event back to the calendar whose color it wears and whose visibility
 * it obeys, so a stand-in holding the id would paint colorless and then be
 * filtered straight out of the grid it was meant to appear in.
 */
function draftEvent(uid: string, calHref: string, body: Record<string, unknown>): CalEvent {
  const start = typeof body.start === 'string' ? body.start : null
  const end = typeof body.end === 'string' ? body.end : null
  const allDay = body.all_day === true
  return {
    uid, id: uid, recurrence_id: null, is_recurring: false, calendar: calHref,
    summary: typeof body.summary === 'string' ? body.summary : null,
    description: typeof body.description === 'string' ? body.description : null,
    location: typeof body.location === 'string' ? body.location : null,
    start, start_is_date: !!start && !start.includes('T'),
    end, end_is_date: !!end && !end.includes('T'), duration: null,
    all_day: allDay, status: null,
    // The create omits `busy` unless the owner picked Free, and an event with
    // no TRANSP is busy — so the stand-in agrees with the DTO that is about to
    // replace it either way.
    busy: body.busy !== false,
    tags: Array.isArray(body.tags) ? (body.tags as string[]) : [],
    has_rrule: false, href: '', etag: '',
  }
}

/**
 * The calendar sidebar's Tasks section: which task lists draw onto the grid.
 *
 * Its own rows rather than a second `Sidebar`: these are task collections
 * borrowed for visibility, so none of the sidebar's collection management —
 * rename, recolor, delete, drag-reorder — applies. A reorder here would
 * PROPPATCH calendar-order onto the *task* collections, rewriting what
 * Tasks.org and Thunderbird read to match a calendar-tab preference.
 *
 * The toggles read the opposite way round from every other row in this
 * sidebar: `shown` is an allowlist, so a solid swatch means "drawn on the
 * calendar" and the default is off.
 */
function CalendarTasksSection({ lists, shown, onShownChange, showDone, onShowDoneChange }: {
  lists: List[]
  shown: Set<string>
  onShownChange: (next: string[]) => void
  showDone: boolean
  onShowDoneChange: () => void
}) {
  const [collapsed, setCollapsed] = useState(false)
  if (!lists.length) return null
  const anyShown = lists.some((l) => shown.has(l.id))
  const toggle = (id: string) =>
    onShownChange(shown.has(id) ? [...shown].filter((x) => x !== id) : [...shown, id])

  return (
    <div className="side-group cal-tasks">
      <div className="group-head">
        <button className="group-caret" aria-expanded={!collapsed}
          aria-label={collapsed ? 'Show task lists' : 'Hide task lists'}
          onClick={() => setCollapsed((c) => !c)}>
          <span className={`caret ${collapsed ? '' : 'open'}`}>›</span>
        </button>
        <span className="group-name">Tasks</span>
        <button className="group-eye" aria-pressed={anyShown}
          title={anyShown ? 'Take task lists off the calendar' : 'Put every task list on the calendar'}
          onClick={() => onShownChange(anyShown ? [] : lists.map((l) => l.id))}>
          {anyShown ? '◉' : '◌'}
        </button>
      </div>
      {!collapsed && (
        <>
          {lists.map((l) => {
            const on = shown.has(l.id)
            return (
              <div key={l.id} className={`side-item ${on ? '' : 'cal-hidden'}`}
                role="checkbox" aria-checked={on} tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); toggle(l.id) }
                }}
                onClick={() => toggle(l.id)}>
                <span className="swatch" style={on
                  ? (cssColor(l.color) ? { background: cssColor(l.color)! } : undefined)
                  : { background: 'transparent',
                      boxShadow: `inset 0 0 0 1.5px ${cssColor(l.color) ?? 'var(--fg-faint)'}` }} />
                <span className="name">{l.name}</span>
                <span className="count">{l.open_count}</span>
              </div>
            )
          })}
          <button className="cal-tasks-done" aria-pressed={showDone} onClick={onShowDoneChange}>
            Completed · {showDone ? 'shown' : 'hidden'}
          </button>
        </>
      )}
    </div>
  )
}

export function CalendarView({ onExpire, sideCollapsed, onToggleSide,
  cursor, onCursorChange,
  hiddenCalendars, onHiddenCalendarsChange,
  archivedCalendars, onArchivedCalendarsChange,
  calTaskLists, onCalTaskListsChange,
  calShowDone, onCalShowDoneChange, fit }: {
  onExpire: () => void
  // The month lives above the tab strip too, so coming back to Calendar returns
  // to where you were rather than snapping to today.
  cursor: Date; onCursorChange: (d: Date) => void
  sideCollapsed: boolean; onToggleSide: () => void
  hiddenCalendars: string[]; onHiddenCalendarsChange: (next: string[]) => void
  archivedCalendars: string[]; onArchivedCalendarsChange: (next: string[]) => void
  // Task lists drawn on the grid. An allowlist — the calendar had no tasks on
  // it before, so it gains none until one is opted in.
  calTaskLists: string[]; onCalTaskListsChange: (next: string[]) => void
  calShowDone: boolean; onCalShowDoneChange: () => void
  // Whether the month fits the pane or grows to its busiest day. Read-only: the
  // choice is made in the settings menu, like the clock and the completed-task
  // toggle, so there is nothing to hand back from here.
  fit: CalendarFit
}) {
  const guard = makeGuard(onExpire)
  const isMobile = useIsMobile()
  const tf = useTimeFormat()
  const { cals, loaded, setCals, eventsFor, requestWindow, setEvents, reload,
    windowErrors } = useCalendarData()
  // Tasks need no fetch of their own: the provider above this already holds
  // every task of every list, and HomeView reads both datasets the same way.
  const { lists: taskLists, tasks, listsLoaded, saveDetail, remove: removeTask } = useTaskData()
  const setCursor = onCursorChange
  // Every calendar is visible by default; this holds the ids the user hid, so a
  // brand-new calendar shows up without any extra write.
  const hidden = useMemo(() => new Set(hiddenCalendars), [hiddenCalendars])
  // Archived calendars are dropped from the grid and sidebar entirely (unlike
  // hidden ones, which still show dimmed). `cals` keeps the full fetched set;
  // `visibleCals` is what the view actually renders and fetches events for.
  const archived = useMemo(() => new Set(archivedCalendars), [archivedCalendars])
  const visibleCals = useMemo(() => cals.filter((c) => !archived.has(c.id)), [cals, archived])
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

  const days = useMemo(() => monthGrid(cursor), [cursor])

  // ── the grid's keyboard walk ──────────────────────────────────────────────
  //
  // ONE tab stop for 42 cells, moved by the arrows — the roving-tabindex
  // pattern a date grid is expected to have. Forty-two real tab stops would be
  // reachable and unusable: crossing the month to get to whatever follows it is
  // not an improvement on not reaching it at all.
  //
  // Held as a DAY KEY rather than an index, so the tab stop survives a month
  // change: the grid always starts on a different weekday, so index 8 is a
  // different date every month, and paging with the arrows would wander.
  const [keyDay, setKeyDay] = useState(() => ymd(new Date()))
  const keyCellRef = useRef<HTMLDivElement>(null)
  // Set when the walk itself moved the focus, so focus follows the arrows —
  // and NOT on an ordinary render, which would steal focus from whatever the
  // owner was actually using.
  const walking = useRef(false)

  useEffect(() => {
    if (!walking.current) return
    walking.current = false
    keyCellRef.current?.focus()
  }, [keyDay, cursor])

  // The focused day must always be ONE of the 42 on screen, or the tab stop
  // disappears and the grid drops out of the tab order entirely. Paging the
  // month is the case: `keyDay` stays where it was and is no longer rendered.
  useEffect(() => {
    const keys = days.map(ymd)
    if (keys.includes(keyDay)) return
    // The same day-of-month where it exists, else the nearest end of the month
    // being shown — which is what a reader who paged here expects to land on.
    const wanted = keyDay.slice(8)
    const inMonth = days.filter((d) => d.getMonth() === cursor.getMonth())
    const match = inMonth.find((d) => ymd(d).slice(8) === wanted)
    setKeyDay(ymd(match ?? inMonth[inMonth.length - 1] ?? days[0]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days])

  // What a screen reader announces on landing in a cell. The visible text is a
  // bare day NUMBER, which out of its column is not a date at all.
  const fmtCellLabel = (d: Date) =>
    d.toLocaleDateString(undefined, {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
    })

  const stepMonth = (by: number) =>
    setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + by, 1))

  const onGridKey = (ev: React.KeyboardEvent) => {
    // Only the CELL's own keys. A chip inside it is a separate control with its
    // own Enter/Space handler, and it stops propagation; anything else in here
    // (a `+N more` button) keeps its native behaviour.
    const step: Record<string, number> = {
      ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7,
    }
    const target = ev.target as HTMLElement
    if (!target.classList.contains('cal-cell')) return
    if (ev.key === 'Enter' || ev.key === ' ') {
      ev.preventDefault()
      setDraft({ date: keyDay })
      return
    }
    const keys = days.map(ymd)
    const at = keys.indexOf(keyDay)
    if (at < 0) return
    let next = at
    if (ev.key in step) next = at + step[ev.key]
    else if (ev.key === 'Home') next = at - (at % 7)
    else if (ev.key === 'End') next = at - (at % 7) + 6
    else if (ev.key === 'PageUp') { ev.preventDefault(); walking.current = true; stepMonth(-1); return }
    else if (ev.key === 'PageDown') { ev.preventDefault(); walking.current = true; stepMonth(1); return }
    else return
    ev.preventDefault()
    // Off either end pages the month, so the walk is not fenced inside one
    // six-week window — the effect above then picks the landing cell.
    if (next < 0 || next > 41) {
      walking.current = true
      stepMonth(next < 0 ? -1 : 1)
      return
    }
    walking.current = true
    setKeyDay(keys[next])
  }

  // The window the grid shows, as the API wants it: the six-week span plus one
  // exclusive day. Both halves of the pair are derived once so the fetch and
  // the cache lookup can never disagree about which window is on screen.
  const from = ymd(days[0])
  const to = useMemo(() => {
    const end = new Date(days[41]); end.setDate(end.getDate() + 1); return ymd(end)
  }, [days])

  // Prune hidden/archived ids for calendars that no longer exist, so the stored
  // sets don't accumulate cruft (ids are random, so a stale one can't leak onto
  // a future calendar). Gated on a real fetch: neither the initial empty state
  // nor the cached seed is evidence a calendar is gone.
  useEffect(() => {
    if (!loaded || !cals.length) return
    const valid = hiddenCalendars.filter((id) => cals.some((c) => c.id === id))
    if (valid.length !== hiddenCalendars.length) onHiddenCalendarsChange(valid)
    const validArch = archivedCalendars.filter((id) => cals.some((c) => c.id === id))
    if (validArch.length !== archivedCalendars.length) onArchivedCalendarsChange(validArch)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cals, loaded])

  // Every calendar's window is fetched and merged; events carry their
  // collection href, so each one still knows where it lives. Visibility is
  // applied as a pure filter afterwards, so toggling a calendar never triggers
  // a refetch. Archiving does, which is why the visible set is what is asked
  // for. The provider owns the request, so a window already fetched this
  // session — or mirrored to disk — paints without going near the network.
  const events = eventsFor(from, to)
  const failedCals = windowErrors(from, to)
  useEffect(() => {
    requestWindow(from, to, visibleCals)
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
  }, [from, to, visibleCals.map((c) => c.id).join(','), requestWindow])

  const reloadHere = () => reload(from, to, visibleCals)
  const patchEvents = (next: (prev: CalEvent[]) => CalEvent[]) => setEvents(from, to, next)

  const calByHref = useMemo(() => new Map(cals.map((c) => [c.href, c] as const)), [cals])
  const calHref = (id: string) => cals.find((c) => c.id === id)?.href ?? ''
  // Which calendar an event lives in — every event now comes from a real fetch.
  const calIdOf = (e: CalEvent) => calByHref.get(e.calendar)?.id || ''
  // Per-event tint, so the combined view keeps each calendar's color.
  const evStyle = (e: CalEvent): CSSProperties | undefined => {
    // Through cssColor: `color` is whatever another CalDAV client wrote into
    // the collection's calendar-color, and `--ev-c` resolves into a plain
    // `background` in app.css — see util.ts.
    const c = cssColor(calByHref.get(e.calendar)?.color)
    return c ? { '--ev-c': c } as CSSProperties : undefined
  }
  // Tasks wear their list's color through the same custom property, so one set
  // of chip rules covers both kinds.
  const taskStyle = (t: Task): CSSProperties | undefined => {
    const c = cssColor(taskColor(t.list))
    return c ? { '--ev-c': c } as CSSProperties : undefined
  }

  // Hidden calendars drop out here — a pure filter, so toggling is instant.
  const visibleEvents = useMemo(
    () => events.filter((e) => !hidden.has(calByHref.get(e.calendar)?.id || '')),
    [events, hidden, calByHref],
  )

  const byDay = useMemo(() => bucketByDay(visibleEvents, days), [visibleEvents, days])

  // ── tasks on the grid ─────────────────────────────────────────────────────
  // An allowlist, so an empty set means no tasks at all rather than all of them.
  const shownTaskLists = useMemo(() => new Set(calTaskLists), [calTaskLists])
  const taskColor = (listId: string) => taskLists.find((l) => l.id === listId)?.color ?? null
  const visibleTasks = useMemo(
    () => tasks.filter((t) =>
      shownTaskLists.has(t.list) && (calShowDone || !(t.completed || t.cancelled))),
    [tasks, shownTaskLists, calShowDone],
  )
  const tasksByDay = useMemo(
    () => bucketTasksByDay(visibleTasks, days), [visibleTasks, days])
  const [taskDetail, setTaskDetail] = useState<Task | null>(null)

  // Drop ids naming a list that no longer exists, so a deletion here or in
  // another CalDAV client doesn't leave the blob accreting them. Gated on a
  // real fetch: the pre-fetch empty state would otherwise clear the setting.
  useEffect(() => {
    if (!listsLoaded || !taskLists.length) return
    const ids = new Set(taskLists.map((l) => l.id))
    const kept = calTaskLists.filter((id) => ids.has(id))
    if (kept.length !== calTaskLists.length) onCalTaskListsChange(kept)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskLists, listsLoaded])

  // The mobile agenda's day, read twice below (rows and the empty state).
  const focusEvents = byDay.get(focusDay) ?? []
  const focusTasks = tasksByDay.get(focusDay) ?? []

  // Optimistically paint an edit onto the events we can represent locally: a
  // non-recurring event, or a single occurrence (scope "this"). Series-wide
  // edits return false — the caller reloads for those instead.
  const applyLocal = (cal: string, uid: string, body: Record<string, unknown>): boolean => {
    const single = body.scope === 'this' && !!body.recurrence_id
    // A UID is only unique WITHIN a collection — the backend keys items on
    // (collection_href, uid), so the same uid in two calendars is two resources.
    // Matching on uid alone painted an edit aimed at one onto both, and the
    // other one's row then disagreed with the server until a full refetch.
    //
    // `!href ||` is load-bearing: `calHref` answers '' until the calendar list
    // has loaded, and without the fallback every optimistic paint on a cold grid
    // would silently match nothing while still reporting success, so nothing
    // would reload to cover for it.
    const href = calHref(cal)
    const mine = (e: CalEvent) => e.uid === uid && (!href || e.calendar === href)
    if (!single && events.some((e) => mine(e) && e.is_recurring)) return false
    patchEvents((evs) => evs.map((e) => {
      if (!mine(e)) return e
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
      // Reveal before painting, not after: a stand-in landing in a calendar the
      // filter is still dropping would flicker in from nowhere a moment later.
      if (hidden.has(cal)) onHiddenCalendarsChange(hiddenCalendars.filter((x) => x !== cal))
      // A repeating create fans out into occurrences server-side, and there is
      // nothing honest to stand in for that — so it alone still waits.
      const repeating = typeof body.repeat === 'string' && body.repeat !== 'none'
      const cid = clientId()
      const uidNew = uidFor(cid)
      if (!repeating) patchEvents((evs) => [...evs, draftEvent(uidNew, calHref(cal), body)])
      const created = await guard(() => api.createEvent(cal, { ...body, client_id: cid }))
      if (!created || created.is_recurring) {
        patchEvents((evs) => evs.filter((e) => e.uid !== uidNew))
        if (created) reloadHere()
        return
      }
      patchEvents((evs) => {
        const next = evs.filter((e) => e.uid !== uidNew && e.uid !== created.uid)
        next.push(created)
        return next
      })
      return
    }
    const painted = applyLocal(cal, uid, body)
    const ok = await guard(() => api.patchEvent(cal, uid, body))
    const moved = !!(ok && moveTo && moveTo !== cal)
    if (moved) {
      await guard(() => api.moveEvent(cal, uid, moveTo!))
      // Reveal the destination, the same two lines the create branch runs and
      // for the same reason. The modal's Calendar picker is populated from
      // `visibleCals`, which includes calendars the user has HIDDEN (hidden is
      // a pure render filter), so moving an event into one made it vanish from
      // the month grid, the mobile agenda and the day popovers with no feedback
      // at all — the event is fine, it is just nowhere the user can see.
      if (hidden.has(moveTo!)) onHiddenCalendarsChange(hiddenCalendars.filter((x) => x !== moveTo))
    }
    if (!ok || !painted || moved) reloadHere()
  }
  const del = async (cal: string, uid: string, opts?: { recurrence_id?: string | null; scope?: EventScope }) => {
    setDraft(null)
    // Drop the affected instances right away; reload rolls back on failure.
    const rid = opts?.recurrence_id
    const scope = opts?.scope || 'all'
    const href = calHref(cal)                 // see applyLocal for the '' fallback
    patchEvents((evs) => evs.filter((e) => {
      if (e.uid !== uid || (href && e.calendar !== href)) return true
      if (scope === 'this' && rid) return e.id !== `${uid}::${rid}`
      if (scope === 'thisandfuture' && rid) return (e.recurrence_id || '') < rid
      return false
    }))
    if ((await guard(() => api.deleteEvent(cal, uid, opts))) === undefined) reloadHere()
  }

  // Desktop drag: move an event chip to another day cell, or drag its resize
  // grip to a new last day. A recurring drop parks in `moveAsk` until the user
  // picks a scope; delta is anchored to the dragged segment's own cell, so
  // continuation segments (and window-clipped events) move correctly.
  const [drag, setDrag] = useState<{ ev: DayEv; fromDay: string; mode: 'move' | 'resize' } | null>(null)
  const [overDay, setOverDay] = useState<string | null>(null)
  const [moveAsk, setMoveAsk] = useState<{ ev: CalEvent; body: Record<string, unknown> } | null>(null)
  const movePress = useRef(false)          // see the scope prompt's overlay

  const dropOnDay = (key: string) => {
    const d = drag
    setDrag(null); setOverDay(null)
    if (!d) return
    // The date arithmetic lives in calendar.ts, where it is tested directly;
    // null means the drag changed nothing. `lastVisible` is the clamp the grid
    // applies when drawing a resize grip: without it, a drop on the clamped cell
    // reads as "end here" and truncates everything past the window.
    const body = dragBody(d.ev, d.fromDay, key, d.mode, ymd(days[41]))
    if (!body) return
    if (d.ev.is_recurring) setMoveAsk({ ev: d.ev, body })
    else save(body, calIdOf(d.ev), d.ev.uid)
  }
  // The scope prompt is a `role="dialog" aria-modal="true"` in its own right —
  // a second one in this file, which is why the modal-contract guard test never
  // saw it: that test greps a FILE for `useEscape(`, and `EventModal` below
  // already satisfied it. Declared modal, it owes the same key.
  //
  // Written as a functional update so the handler identity never changes and the
  // listener is not re-bound on every drag: when nothing is asking, Escape here
  // returns the same state and React re-renders nothing.
  useEscape(useCallback(() => setMoveAsk((a) => (a ? null : a)), []))

  const pickMoveScope = (scope: EventScope) => {
    if (!moveAsk) return
    save({ ...moveAsk.body, recurrence_id: moveAsk.ev.recurrence_id, scope },
      calIdOf(moveAsk.ev), moveAsk.ev.uid)
    setMoveAsk(null)
  }

  // Desktop "+N more": a popover anchored to the day cell listing every event.
  const [more, setMore] = useState<{ day: string; x: number; y: number } | null>(null)

  // ── the fixed window ──────────────────────────────────────────────────────
  // Mobile is left out on purpose rather than overlooked: its cells carry dots
  // instead of chips, and the day agenda renders *below* the grid inside the
  // same scroller, so pinning the grid to the pane would squeeze the agenda off
  // the screen. There is nothing on a mobile cell for a busy day to stretch.
  const fitted = fit === 'fixed' && !isMobile
  const scrollRef = useRef<HTMLDivElement>(null)
  const [capacity, setCapacity] = useState(CELL_MAX)

  // Re-measured after every render — the cap has to answer to a month change, a
  // font change and a text-size change alike, and none of those resizes the
  // pane. It settles in one extra pass and cannot oscillate: a fixed row's
  // height comes from the grid, not from what the cell holds, so the cap is a
  // function of the layout and not of its own last answer.
  useLayoutEffect(() => {
    if (!fitted) {
      setCapacity((prev) => (prev === CELL_MAX ? prev : CELL_MAX))
      return
    }
    const next = measureCells(scrollRef.current)
    // null is "nothing to measure yet" — keep the last usable answer rather
    // than blanking every cell (which is also what jsdom always reports).
    if (next !== null) setCapacity((prev) => (prev === next ? prev : next))
  })

  // A window resize changes the pane without re-rendering anything, so the
  // effect above would never hear about it.
  useEffect(() => {
    const el = scrollRef.current
    if (!fitted || !el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => {
      const next = measureCells(el)
      if (next !== null) setCapacity((prev) => (prev === next ? prev : next))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [fitted])
  const calApi = {
    create: (name: string, color?: string | null) => guard(() => api.createCalendar(name, color)),
    update: (id: string, body: { name?: string; color?: string | null }) =>
      guard(() => api.updateCalendar(id, body)),
    remove: (id: string) => guard(() => api.deleteCalendar(id)),
    reorder: (ids: string[]) => guard(() => api.reorderCalendars(ids)),
  }

  const todayKey = ymd(new Date())
  const lastKey = ymd(days[41])            // final visible day, for resize grips (and dropOnDay's clamp)
  // Where new events land by default: the first shown (non-hidden) calendar,
  // among those not archived; else the first visible one.
  const defaultCal = visibleCals.find((c) => !hidden.has(c.id))?.id || visibleCals[0]?.id || ''
  // Archive supersedes the eye-toggle: also drop any stale hidden entry so a
  // restored calendar always comes back fully visible, not dimmed.
  const archiveCal = (id: string) => {
    onArchivedCalendarsChange([...archivedCalendars, id])
    if (hidden.has(id)) onHiddenCalendarsChange(hiddenCalendars.filter((x) => x !== id))
  }

  return (
    <div className="work">
      {/* Sidebar keeps the full `cals` set (so reorder/drag operate on the real
          order and send the full id list); `archivedIds` hides archived rows at
          render time only. */}
      <Sidebar title="Calendars" placeholder="Calendar" items={cals}
        countOf={(c) => c.event_count} onItems={setCals} api={calApi}
        collapsed={sideCollapsed} onToggle={onToggleSide}
        hiddenIds={hidden} onHiddenChange={onHiddenCalendarsChange}
        archivedIds={archived} onArchive={archiveCal}
        extra={
          <CalendarTasksSection lists={taskLists} shown={shownTaskLists}
            onShownChange={onCalTaskListsChange}
            showDone={calShowDone} onShowDoneChange={onCalShowDoneChange} />
        } />

      <div className="content">
        <div className="cal-head">
          <button className="icon-btn" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}>‹</button>
          <button className="btn ghost" onClick={() => { const n = new Date(); setCursor(new Date(n.getFullYear(), n.getMonth(), 1)) }}>Today</button>
          <button className="icon-btn" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}>›</button>
          <span className="cal-title">{MONTHS[cursor.getMonth()]} {cursor.getFullYear()}</span>
          <span className="spacer" />
          {visibleCals.length > 0 && !isMobile && (
            <button className="btn" onClick={() => setDraft({ date: todayKey })}>New event</button>
          )}
        </div>
        {visibleCals.length === 0 ? (
          // Same three-way as the tasks pane: an empty `cals` before the fetch
          // lands is ignorance, not an empty account.
          <div className="empty" aria-busy={!loaded || undefined}>
            {!loaded
              ? 'Loading…'
              : cals.length === 0
                ? 'Create a calendar to get started.'
                : 'All calendars are archived — restore one from Settings.'}
          </div>
        ) : (
          <div ref={scrollRef} className={`cal-scroll${fitted ? ' fixed' : ''}`}>
            {/* A month that is SHORT must say so. The fan-out keeps whatever
                loaded rather than blanking the grid on one calendar's 502, and
                without this the user reads a partial month as a complete one —
                the failure mode the all-or-nothing fetch at least made obvious.
                Retry re-requests the whole window; one unhealthy collection is
                usually unhealthy for all of them. */}
            {failedCals.length > 0 && (
              <div className="cal-partial" role="status">
                Couldn&rsquo;t load {failedCals.join(', ')} — this month may be
                missing events.{' '}
                <button className="btn ghost" onClick={reloadHere}>
                  Retry
                </button>
              </div>
            )}
            {/* A GRID, and the day cells take a roving tabindex — the pattern a
                date grid is expected to have, and the one screen readers
                announce as a grid rather than as 42 anonymous divs. One tab
                stop for the whole month; the arrows walk it. Every interactive
                surface in here used to be a plain `<div>` with an `onClick`,
                so there was no key sequence that opened an event or created one
                on a given day — while `+N more` two lines down is a real
                `<button>` and the mobile agenda rows are buttons too, which is
                what made the omission look deliberate rather than uniform. */}
            <div className="cal-grid" role="grid" aria-label="Month"
              onKeyDown={onGridKey}>
              {DOW.map((d) => (
                <div key={d} className="cal-dow" role="columnheader">{d}</div>
              ))}
              {days.map((d) => {
                const key = ymd(d)
                const inMonth = d.getMonth() === cursor.getMonth()
                const dayEvents = byDay.get(key) ?? []
                const dayTasks = tasksByDay.get(key) ?? []
                // One cap over both kinds, so the "+N more" count is the whole
                // remainder rather than the events' share of it. Events lead:
                // they hold a span, tasks are a single deadline on the day.
                const total = dayEvents.length + dayTasks.length
                const room = chipsShown(total, fitted ? capacity : CELL_MAX, fitted)
                const shownEvents = dayEvents.slice(0, room)
                const shownTasks = dayTasks.slice(0, Math.max(0, room - shownEvents.length))
                const hiddenCount = total - shownEvents.length - shownTasks.length
                return (
                  <div key={key}
                    className={`cal-cell ${inMonth ? '' : 'dim'} ${key === todayKey ? 'today' : ''} ${isMobile && key === focusDay ? 'focus' : ''} ${drag && overDay === key ? 'drag-over' : ''}`}
                    role="gridcell"
                    aria-label={fmtCellLabel(d)}
                    // THE roving tabindex: exactly one cell is in the tab order
                    // at a time, and the arrows move which. `key === keyDay`
                    // rather than an index so the tab stop survives a month
                    // change landing on a different number of leading blanks.
                    tabIndex={key === keyDay ? 0 : -1}
                    data-day={key}
                    ref={key === keyDay ? keyCellRef : undefined}
                    onFocus={() => setKeyDay(key)}
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
                      (dayEvents.length > 0 || dayTasks.length > 0) && (
                        <span className="ev-dots">
                          {dayEvents.slice(0, 6).map((e) => (
                            <i key={eventKey(e)} className={`ev-dot ${e.all_day ? 'allday' : ''}`} style={evStyle(e)} />
                          ))}
                          {/* The kind goes in a DATA ATTRIBUTE, not the class
                              list. `.task` is a GLOBAL rule — the Tasks pane's
                              row: `display:flex`, a border and
                              `padding: var(--row-y) var(--gutter)` — so a dot
                              wearing the bare class inherited 11px/14px of
                              padding and rendered as a 28x23 SLAB instead of a
                              5x5 mark, swamping the day number beside it.
                              Measured in Chromium, phone width only, because
                              this branch is the phone's.

                              That is the second time this exact collision has
                              shipped (see `TodayView`'s kind mark, fixed the
                              same way): `.task` is the one bare class in
                              app.css carrying layout, and any element given it
                              as a modifier picks the whole row rule up. */}
                          {dayTasks.slice(0, Math.max(0, 6 - dayEvents.length)).map((t) => (
                            <i key={taskKey(t)} className="ev-dot" data-kind="task"
                              style={taskStyle(t)} />
                          ))}
                        </span>
                      )
                    ) : (
                      <>
                        {shownEvents.map((e) => {
                          const evLast = lastDayOf(e)
                          const resizable = key === (evLast > lastKey ? lastKey : evLast)
                          return (
                            // Keyed by collection too: `id` is unique per
                            // rendered instance of a SERIES (uid, or
                            // uid::recurrence_id), and a UID is only unique
                            // within one collection — so the same event copied
                            // to, or subscribed from, a second calendar gave two
                            // chips one key. React then drops one and can bind
                            // the wrong click target to the other.
                            <div key={eventKey(e)}
                              className={`cal-ev ${e.all_day ? 'allday' : ''} ${e.cont ? 'cont' : ''}`}
                              style={evStyle(e)}
                              dir={textDir(e.summary)}
                              title={e.is_recurring ? `${e.summary || ''} (repeating)` : (e.summary || '')}
                              // Operable, and OUT of the roving walk: a chip is
                              // reached by tabbing on from the focused cell, so
                              // the arrows stay the grid's. The sidebar row in
                              // this same file is the in-file precedent for the
                              // role/tabIndex/keydown trio.
                              role="button"
                              tabIndex={0}
                              onKeyDown={(ev) => {
                                if (ev.key !== 'Enter' && ev.key !== ' ') return
                                ev.preventDefault()
                                ev.stopPropagation()
                                setDraft({ event: e })
                              }}
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
                                <span className="t">{fmtClock(e.start, tf)}</span>
                              )}
                              {e.is_recurring && <span className="recur" aria-hidden="true">↻ </span>}
                              {e.cont && <span className="t" aria-hidden="true">‥ </span>}
                              {/* A title too long for its cell is cut by CSS
                                  (`text-overflow: ellipsis`), never here — the
                                  browser clips the shaped line and paints an
                                  ellipsis over it. Cutting the STRING instead
                                  would break Arabic letter joining: the last
                                  surviving letter falls back to its isolated
                                  form, which is often wider than the medial one
                                  it replaced, so a "shortened" title can render
                                  longer than the one it shortened. `title=`
                                  above keeps the whole thing a hover away, and
                                  <bdi> stops an RTL title reordering the clock
                                  prefix and the ↻ around it. */}
                              <bdi>{e.summary || '(untitled)'}</bdi>
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
                        {shownTasks.map((t) => {
                          const timed = !!t.due && t.due.includes('T') && !t.due_is_date
                          const done = t.completed || t.cancelled
                          return (
                            <div key={taskKey(t)} className={`cal-task ${done ? 'done' : ''}`}
                              style={taskStyle(t)} dir={textDir(t.summary)} title={t.summary || ''}
                              // Same treatment as the event chip beside it. The
                              // finding names the event chip; a task chip in the
                              // same cell that stayed unreachable would be the
                              // same bug with a different selector.
                              role="button"
                              tabIndex={0}
                              onKeyDown={(ev) => {
                                if (ev.key !== 'Enter' && ev.key !== ' ') return
                                ev.preventDefault()
                                ev.stopPropagation()
                                setTaskDetail(t)
                              }}
                              onClick={(ev) => { ev.stopPropagation(); setTaskDetail(t) }}>
                              <span className="tick" aria-hidden="true">{done ? '☑' : '☐'}</span>
                              {timed && <span className="t">{fmtClock(t.due!, tf)}</span>}
                              {/* Cut by CSS, never by the string — see the event
                                  chip above for why that distinction matters. */}
                              <bdi>{t.summary || '(untitled)'}</bdi>
                            </div>
                          )
                        })}
                        {hiddenCount > 0 && (
                          <button className="cal-more" onClick={(ev) => {
                            ev.stopPropagation()
                            const r = ev.currentTarget.closest('.cal-cell')!.getBoundingClientRect()
                            setMore({ day: key, x: r.left, y: r.top })
                          }}>+{hiddenCount} more</button>
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
                {focusEvents.map((e) => (
                  <AgendaEvent key={eventKey(e)} ev={e} day={focusDay} style={evStyle(e)}
                    onOpen={() => setDraft({ event: e })} />
                ))}
                {focusTasks.map((t) => (
                  <AgendaTask key={taskKey(t)} task={t} style={taskStyle(t)}
                    onOpen={() => setTaskDetail(t)} />
                ))}
                {focusEvents.length === 0 && focusTasks.length === 0 && (
                  <div className="agenda-empty">Nothing this day.</div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {draft && (
        <EventModal draft={draft} cals={visibleCals} onClose={() => setDraft(null)}
          initialCal={draft.event ? calIdOf(draft.event) : defaultCal}
          onSave={(body, cal, uid) => {
            // Existing events are patched where they live, then relocated if a
            // different calendar was picked; new events go straight to the pick.
            if (uid && draft.event) save(body, calIdOf(draft.event), uid, cal)
            else save(body, cal)
          }}
          onDelete={(uid, opts) => del(draft.event ? calIdOf(draft.event) : defaultCal, uid, opts)} />
      )}

      {/* The tasks tab's own editor, so a task edited from the calendar goes
          down the same optimistic path and paints the same way. Editing only —
          creating a task from a calendar cell would need a list picker and a
          quick-add, which is what the tasks tab is. */}
      {taskDetail && (
        <TaskModal task={taskDetail} lists={taskLists} defaultList={taskDetail.list}
          onClose={() => setTaskDetail(null)}
          onCreate={() => {}} onMultiple={() => {}}
          onSave={(patch) => { void saveDetail(taskDetail, patch); setTaskDetail(null) }}
          onDelete={() => { void removeTask(taskDetail); setTaskDetail(null) }} />
      )}

      {more && (
        <DayPopover day={more.day} x={more.x} y={more.y} events={byDay.get(more.day) ?? []}
          tasks={tasksByDay.get(more.day) ?? []}
          styleOf={evStyle} taskStyleOf={taskStyle}
          onOpen={(e) => { setMore(null); setDraft({ event: e }) }}
          onOpenTask={(t) => { setMore(null); setTaskDetail(t) }}
          onClose={() => setMore(null)} />
      )}

      {moveAsk && (
        <div className="overlay"
          onMouseDown={(ev) => { movePress.current = ev.target === ev.currentTarget }}
          onClick={(ev) => {
            if (ev.target === ev.currentTarget && movePress.current) setMoveAsk(null)
            movePress.current = false
          }}>
          <div className="modal" role="dialog" aria-modal="true" aria-label="Repeating event"
            onClick={(ev) => ev.stopPropagation()}>
            <div className="modal-head">
              <span className="modal-title">Repeating event</span>
              <button className="icon-btn" onClick={() => setMoveAsk(null)} aria-label="Close">✕</button>
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
  const lang = inputLang(useTimeFormat())
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
  // A VEVENT can carry its length as DURATION instead of DTEND — the shape
  // DAVx5 and the phone clients write — and those arrive with `end: null`.
  // Defaulting the picker to 10:00 for them meant any save, including a pure
  // rename, rewrote the event's end: `commit()` sends start AND end for a
  // non-recurring event, and `_apply_event_fields` deletes DURATION whenever a
  // dtend is supplied, so the original span was gone for good. A zero-length
  // event also stops blocking booking slots (busy_intervals only counts an
  // interval when end > start). `calendar.ts` already got this right on the
  // drag path — the modal was the outlier.
  const derivedEnd = e && !e.end && e.start ? endFromDuration(e.start, e.duration) : null
  const [end, setEnd] = useState(() => {
    if (!e?.end) return derivedEnd ?? `${baseDate}T10:00`
    if (e.end.includes('T')) return toLocalInput(e.end)
    // All-day DTEND is exclusive — show the inclusive last day in the picker.
    const inclusive = shiftYmd(e.end.slice(0, 10), -1)
    const startDay = e.start ? e.start.slice(0, 10) : inclusive
    return inclusive < startDay ? startDay : inclusive
  })
  // Nothing to reconstruct the span from: rather than send a fabricated end and
  // destroy whatever the resource actually holds, leave `end` out of the write.
  const endUnknown = !!e && !e.end && !derivedEnd
  const [location, setLocation] = useState(e?.location || '')
  const [description, setDescription] = useState(e?.description || '')
  // Held as a LIST, not as a comma-joined string that is re-split on save.
  // `CATEGORIES:Home\,Garden` is ONE category per RFC 5545 — the backend reads
  // it with icalendar's `.cats` and writes it back escaped — so any
  // delimiter-joined text field destroys a category another CalDAV client
  // authored with a comma in it. That is `TagInput`'s whole reason for existing
  // on the task side; the event editor was simply never converted.
  const [tags, setTags] = useState<string[]>(e?.tags || [])
  /**
   * Whether this event consumes the owner's time — iCalendar's TRANSP, the
   * field Apple Calendar labels "Busy/Free" and Thunderbird "Show Time As".
   *
   * `e?.busy ?? true` rather than `!!e?.busy`, because a new event has no DTO
   * to read and the answer for one is BUSY: that is the RFC's default for an
   * absent property, so the control opens agreeing with what the server would
   * store if it were never touched.
   */
  const [busy, setBusy] = useState(e?.busy ?? true)
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
  // Ticking "all day" on a TIMED event has to answer the same question
  // `endIsExclusive`/`lastDayOf` answer everywhere else the event is shown or
  // dragged: a DTEND sitting exactly on local midnight ends at the START of that
  // day, so the last day it covers is the one before. Slicing ten characters off
  // reinterpreted that exclusive instant as an inclusive last day, and
  // `endOut = shiftYmd(clampedEnd, 1)` below then added another on top — a
  // 20:00-to-midnight event became two days in every CalDAV client, after an
  // edit the user believed only changed the representation.
  //
  // The `includes('T')` guard is what makes this safe, and it is the whole fix:
  // for an event that is ALREADY all-day, `end` was seeded as the inclusive day
  // (no `T`) further up, so subtracting again would shorten every real all-day
  // event by a day on every save.
  const endLastDay = () => {
    if (!end.includes('T')) return end.slice(0, 10)
    const inclusive = end.slice(11, 16) === '00:00'
      ? shiftYmd(end.slice(0, 10), -1)
      : end.slice(0, 10)
    return inclusive < startVal ? startVal : inclusive
  }
  const endVal = allDay ? endLastDay() : (end.includes('T') ? end : `${end}T10:00`)

  // Moving the start drags the end along, preserving the event's duration — no
  // more fixing the end by hand after every start change.
  const changeStart = (v: string) => {
    setStart(v)
    if (!v) return
    if (allDay) {
      // An all-day span's length is a whole number of calendar *days*, not of
      // milliseconds. Measuring it in milliseconds made a span containing a
      // spring-forward come out at 47h instead of 48h, so re-anchoring it to a
      // date outside that week landed the end a day short — the event quietly
      // lost a day when the user had only touched the start.
      const n = daysBetween(startVal, endVal)
      if (isNaN(n)) return
      setEnd(shiftYmd(v, Math.max(0, n)))
      return
    }
    const oldS = new Date(startVal)
    const oldE = new Date(endVal)
    const newS = new Date(v)
    if (isNaN(oldS.getTime()) || isNaN(oldE.getTime()) || isNaN(newS.getTime())) return
    // A timed event's duration really is an elapsed span, so milliseconds are
    // the right unit here — an hour-long meeting stays an hour across a DST edge.
    const shifted = new Date(newS.getTime() + Math.max(0, oldE.getTime() - oldS.getTime()))
    setEnd(`${ymd(shifted)}T${pad(shifted.getHours())}:${pad(shifted.getMinutes())}`)
  }

  // What actually goes on the wire: end never precedes start, and an all-day
  // range converts back from the inclusive picker to an exclusive DTEND.
  const clampedEnd = endVal < startVal ? startVal : endVal
  const startOut = startVal
  const endOut = allDay ? shiftYmd(clampedEnd, 1) : clampedEnd

  // Sent only when they actually differ from what the event holds. `commit`
  // used to include `tags` on EVERY save, so an edit that only changed the title
  // rewrote CATEGORIES too — which is how the re-split above reached events the
  // user never touched the tags of. `sameValue` is TaskModal's precedent.
  const tagFields = (): Record<string, unknown> =>
    (e && sameValue(tags, e.tags || [])) ? {} : { tags }
  /**
   * `busy`, only when it actually differs from what the event holds.
   *
   * The same discipline `tagFields` keeps, and it is load-bearing for the same
   * reason it is there: the backend WRITES the property when the key is
   * present, so sending it on every save would stamp `TRANSP:OPAQUE` onto every
   * event this app touches — including ones another CalDAV client deliberately
   * left the property off, and including a pure rename. Invariant #2: a
   * resource's properties are not ours to rewrite in passing.
   *
   * On a NEW event the same rule reads the other way round: there is nothing to
   * compare against, and an omitted key means no TRANSP at all, which is
   * already busy. So only Free is worth saying.
   */
  const busyFields = (): Record<string, unknown> =>
    (e ? busy === e.busy : busy) ? {} : { busy }
  const repeatFields = (): Record<string, unknown> => {
    if (repeat === 'keep') return {}          // leave the existing rule untouched
    const b: Record<string, unknown> = { repeat }
    if (repeat !== 'none' && repeatUntil) b.repeat_until = repeatUntil
    return b
  }

  const commit = (scope: EventScope) => {
    if (!e) {
      onSave({ summary, all_day: allDay, start: startOut, end: endOut,
               location, description, tags, ...busyFields(), ...repeatFields() }, calPick)
      return
    }
    const details = { summary, location, description, ...tagFields(), ...busyFields() }
    // An event whose span we could not reconstruct sends no end at all, so the
    // stored DTEND/DURATION is left exactly as its author wrote it.
    const times = endUnknown
      ? { start: startOut }
      : { start: startOut, end: endOut }
    if (recurring && scope === 'all') {
      // A changed time plus recurrence_id tells the server to shift the whole
      // series by the same offset (EXDATEs and overrides move along). Untouched
      // times are omitted — resending an occurrence's slot as the master start
      // would slide the series arbitrarily.
      const shift = timeChanged ? { ...times, recurrence_id: e.recurrence_id } : {}
      onSave({ ...details, ...shift, ...repeatFields(), scope: 'all' }, calPick, e.uid)
    } else if (recurring) {
      // "This & following" carries the repeat too. The backend splits the series
      // at the anchor and re-rules the TAIL from `edit.rrule` — verified against
      // `ical.split_series` directly: a tail asked for weekly comes back
      // `RRULE:FREQ=WEEKLY`, and one asked for "does not repeat" comes back with
      // no RRULE at all. Dropping `repeatFields()` here meant a user who changed
      // Repeat and then answered the scope prompt with this button got no rule
      // change, no error and no warning — the modal closed and the grid
      // repainted as if it had worked.
      //
      // "This event" still cannot: it writes a RECURRENCE-ID override for one
      // occurrence, and a rule on an override means nothing. That combination is
      // REFUSED in `pickScope` rather than sent-and-dropped — the one thing that
      // is not an answer is closing as if it had worked.
      const cadence = scope === 'thisandfuture' ? repeatFields() : {}
      onSave({ ...details, ...times, ...cadence, recurrence_id: e.recurrence_id, scope },
             calPick, e.uid)
    } else {
      onSave({ ...details, ...times, ...repeatFields() }, calPick, e.uid)
    }
  }

  const onSaveClick = () => { if (recurring) setScopeAsk('save'); else commit('all') }
  const onDeleteClick = () => { if (!e) return; recurring ? setScopeAsk('delete') : onDelete(e.uid) }
  // See the overlay below.
  const scrimPress = useRef(false)

  // A cadence change cannot ride on "This event": that writes a RECURRENCE-ID
  // override for one occurrence, and an RRULE on an override is meaningless. The
  // other two scopes carry it — "All events" always did, and "This & following"
  // now does, because the backend's `split_series` re-rules the tail.
  const cadenceBlocked = scopeAsk === 'save' && repeat !== 'keep'
  const [scopeErr, setScopeErr] = useState<string | null>(null)

  const pickScope = (scope: EventScope) => {
    if (scopeAsk === 'save' && scope === 'this' && repeat !== 'keep') {
      // Sent back to the form with the change still in it, rather than closed as
      // if it had worked. The user can pick another scope, or set Repeat back to
      // "Keep current schedule" and save this occurrence alone.
      setScopeAsk(null)
      setScopeErr('A repeat change cannot apply to a single occurrence. '
        + 'Use “This & following” or “All events”, or set Repeat back to '
        + '“Keep current schedule”.')
      return
    }
    setScopeErr(null)
    if (scopeAsk === 'delete' && e) onDelete(e.uid, { recurrence_id: e.recurrence_id, scope })
    else commit(scope)
    setScopeAsk(null)
  }

  // The modal contract every other dialog keeps. This one — the calendar tab's
  // only editor for creating, editing and deleting events — declared
  // `aria-modal="true"` with no focus trap and no keydown listener at all, so a
  // keyboard or screen-reader user had no way out of it but the mouse.
  //
  // The existing guard test greps components that ALREADY import `useEscape`,
  // which is structurally incapable of catching a dialog that never adopted it.
  //
  // Escape unwinds ONE step. The scope prompt renders in place of the form, with
  // the form's state still held behind it; a bare `onClose` there threw away a
  // filled-in event because the user pressed Escape at a prompt they only meant
  // to back out of — and the prompt's own Cancel button does exactly this.
  useEscape(useCallback(() => {
    if (scopeAsk) { setScopeAsk(null); return }
    onClose()
  }, [scopeAsk, onClose]))

  return (
    <div className="overlay"
      onMouseDown={(ev) => { scrimPress.current = ev.target === ev.currentTarget }}
      onClick={(ev) => {
        if (ev.target === ev.currentTarget && scrimPress.current) onClose()
        scrimPress.current = false
      }}>
      <div className="modal" role="dialog" aria-modal="true"
        aria-label={e ? (recurring ? 'Repeating event' : 'Event') : 'New event'}
        onClick={(ev) => ev.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{e ? (recurring ? 'Repeating event' : 'Event') : 'New event'}</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {scopeAsk ? (
          <div className="scope-choose">
            <p className="scope-q">
              {scopeAsk === 'delete' ? 'Delete which events?' : 'Apply changes to which events?'}
            </p>
            {cadenceBlocked && (
              <p className="scope-hint" role="status">
                The repeat change needs “This &amp; following” or “All events” — a single
                occurrence has no schedule of its own.
              </p>
            )}
            <button className="btn" onClick={() => pickScope('this')}>This event</button>
            <button className="btn" onClick={() => pickScope('thisandfuture')}>This &amp; following</button>
            <button className="btn" onClick={() => pickScope('all')}>All events</button>
            <button className="btn ghost" onClick={() => setScopeAsk(null)}>Cancel</button>
          </div>
        ) : (
          <>
            {scopeErr && <p className="scope-hint" role="alert">{scopeErr}</p>}
            <div className="field">
              <label className="label" htmlFor="ev-title">Title</label>
              <input className="input" id="ev-title" autoFocus value={summary} onChange={(ev) => setSummary(ev.target.value)} />
            </div>
            <label className="chip" style={{ alignSelf: 'flex-start', cursor: 'pointer' }}>
              <input type="checkbox" checked={allDay} onChange={(ev) => setAllDay(ev.target.checked)} /> all day
            </label>
            <div className="field-row">
              <div className="field">
                <label className="label" htmlFor="ev-start">Start</label>
                <DateTimeInput className="input" id="ev-start"
                  type={allDay ? 'date' : 'datetime-local'} value={startVal}
                  lang={lang} onChange={(ev) => changeStart(ev.target.value)} />
              </div>
              <div className="field">
                <label className="label" htmlFor="ev-end">{allDay ? 'End (last day)' : 'End'}</label>
                <DateTimeInput className="input" id="ev-end"
                  type={allDay ? 'date' : 'datetime-local'} value={endVal}
                  lang={lang} min={startVal} onChange={(ev) => setEnd(ev.target.value)} />
              </div>
            </div>
            <div className="field">
              <label className="label" htmlFor="ev-repeat">Repeat</label>
              <select className="input" id="ev-repeat" value={repeat} onChange={(ev) => setRepeat(ev.target.value)}>
                {recurring && <option value="keep">Keep current schedule</option>}
                {REPEATS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            {/* WHAT THIS DOES TO THE OWNER'S AVAILABILITY, said in the words
                the consequence is about rather than in the property's.
                "Transparency" is what the wire calls it and what nobody means;
                Apple says Busy/Free and so does this.

                A select rather than a checkbox, because the two values are two
                statements and neither is the negation of the other on screen —
                "not busy" reads as "unset" where "Free" reads as a decision.
                Same shape as Repeat above it, which is the other field here
                whose value is a choice among named behaviours.

                Placed under the times, since it is a statement ABOUT that span
                and means nothing without one. */}
            <div className="field">
              <label className="label" htmlFor="ev-busy">Show as</label>
              <select className="input" id="ev-busy" value={busy ? 'busy' : 'free'}
                onChange={(ev) => setBusy(ev.target.value === 'busy')}>
                <option value="busy">Busy</option>
                <option value="free">Free</option>
              </select>
              {/* Only on the arm that changes something, and only for the
                  half of it a person cannot see: an event that blocks is what
                  every event does, and saying so would be a line of chrome
                  under every event in the app. */}
              {!busy && (
                <p className="field-hint">
                  Free time can still be booked — this will not block a slot on
                  your booking links.
                </p>
              )}
            </div>
            {repeat !== 'keep' && repeat !== 'none' && (
              <div className="field">
                <label className="label" htmlFor="ev-until">Repeat until (optional)</label>
                <DateTimeInput className="input" id="ev-until" type="date" value={repeatUntil}
                  onChange={(ev) => setRepeatUntil(ev.target.value)} />
              </div>
            )}
            {cals.length > 1 && (
              <div className="field">
                <label className="label" htmlFor="ev-cal">Calendar</label>
                <select className="input" id="ev-cal" value={calPick} onChange={(ev) => setCalPick(ev.target.value)}>
                  {cals.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
            )}
            <div className="field">
              <label className="label" htmlFor="ev-location">Location</label>
              <input className="input" id="ev-location" value={location} onChange={(ev) => setLocation(ev.target.value)} />
            </div>
            <div className="field">
              <label className="label" htmlFor="ev-notes">Notes</label>
              <textarea className="input" id="ev-notes" rows={2} value={description} onChange={(ev) => setDescription(ev.target.value)} />
            </div>
            <div className="field">
              <label className="label">Tags</label>
              <TagInput label="Tags" value={tags} onChange={setTags} />
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

