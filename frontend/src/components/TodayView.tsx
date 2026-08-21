// The Today tab: one day, held in state, that the owner actually works.
//
// Every other task surface in this app renders a QUERY — "what is due today",
// recomputed from the wire on every paint, so the list moves under you all day.
// This one renders a SNAPSHOT. The backend freezes what a day held the first
// time it was opened (`day_plan`), and from then on the day is something the
// owner arranges: adding to it, ticking it off, dropping what is not going to
// happen. That is why the rows here come from `/api/day` and not from `tasks`.
//
// Two truths meet on this screen and only one of them lives in the day plan:
//
//   * whether a TASK is done is its VTODO STATUS, and `useTaskData().toggle` is
//     the single place in this app that writes it (through `api.complete`). A
//     day entry naming a task is a POINTER — the wire deliberately stores no
//     title and no done flag for one — so ticking a task row here goes through
//     that same call. Recording it on the entry as well would be a second
//     answer to the same question, and the two would disagree the moment the
//     task was ticked in the Tasks pane, on a phone, or in Thunderbird.
//   * whether a NOTE is done is the entry's own `done_at`, because a note
//     exists nowhere but in the day. That one is a PATCH.
//
// ── the midnight problem ───────────────────────────────────────────────────
//
// Nothing else in this app recomputes on a day boundary, and nothing else has
// to: `rev` only moves when the server publishes, and HomeView computes today
// at render, so its worst case is a stale-looking card that repaints on the
// next SSE bump. A STATEFUL surface cannot get away with that. Left open
// overnight — which is the normal way a daily surface is used — a day key
// computed once at mount would still say yesterday, and every write this view
// makes carries the day in its URL. The check-off the owner made over breakfast
// would land on YESTERDAY's plan: it would not appear on the screen in front of
// them, and it would silently rewrite a day that is supposed to be a finished
// record. So the day is state, a timer re-reads the wall clock at the next
// local midnight, and every write carries the key explicitly.

import {
  useCallback, useEffect, useMemo, useRef, useState, type CSSProperties,
} from 'react'
import { api, clientId, type CalEvent, type DayEntry, type DayPlan, type Task } from '../api'
import { useCalendarData, useTaskData } from '../data'
import { addDays, cssColor, dayKey, isOverdue, makeGuard, textDir, ymd } from '../util'
import { fmtDue } from '../time'
import { useTimeFormat } from '../timeformat'
import { sortTasks, taskKey } from '../order'
import { bucketByDay, eventKey, monthGrid, type DayEv } from '../calendar'
import { parseEntry, type ParsedEntry } from '../daytext'
import { AgendaEvent } from './DayPopover'

/** How far past the computed midnight the rollover timer aims.
 *
 *  `setTimeout` is allowed to fire a whisker EARLY, and a callback that runs at
 *  23:59:59.999 reads the wall clock as still yesterday — it would set the day
 *  it already holds and arm the next timer for a midnight 24 hours away, so the
 *  surface would sit on the wrong day for a whole day. Half a second of slack
 *  is invisible and removes the whole class. */
const MIDNIGHT_SLACK_MS = 500

/** How far ahead the "next 7 days" suggestions reach. Same horizon as the Home
 *  dashboard's Upcoming module, so the two never disagree about what is soon. */
const SOON_DAYS = 7

/**
 * A day's entries in reading order, as a new array.
 *
 * The same total key the server reads them by (`store._DAY_ORDER`:
 * `position IS NULL, position, created_at, entry_id`) — unpositioned rows TRAIL
 * rather than lead, and the last two keys are what make it total. Re-applied
 * here rather than trusting the fetched order because the array is edited
 * locally between fetches: an optimistic add is appended, and a row that
 * painted at the bottom must not jump somewhere else when the server's copy of
 * the day arrives. `created_at` is millisecond-resolution, so a whole snapshot
 * can share one value; without `entry_id` behind it two rows would be free to
 * swap places between two renders of an unchanged day.
 */
export function orderEntries(entries: DayEntry[]): DayEntry[] {
  return [...entries].sort((a, b) => {
    const an = a.position == null
    const bn = b.position == null
    if (an !== bn) return an ? 1 : -1
    if (!an && !bn && a.position !== b.position) return a.position! - b.position!
    return a.created_at.localeCompare(b.created_at) || a.entry_id.localeCompare(b.entry_id)
  })
}

/**
 * The `due` a parsed line should author, on the day being planned.
 *
 * A time with no date is the ordinary reading — "gym at 7" names an hour and
 * leaves the day alone — and `daytext` refuses to guess a day from the clock on
 * purpose, so supplying one is the caller's job. This view is planning a
 * particular day already, which makes it the right caller: the day on screen is
 * the day the line lands on, including after a midnight rollover.
 */
export function dueFromParse(p: ParsedEntry, day: string): string {
  const date = p.dueDate || day
  return p.dueTime ? `${date}T${p.dueTime}` : date
}

export function TodayView({ rev, onExpire, hiddenCalendars = [], archivedCalendars = [] }: {
  rev: number
  onExpire: () => void
  // Read-only here, exactly as on the Home dashboard: the calendar strip honours
  // the Calendar tab's visibility choices, and that tab stays the sole owner of
  // editing (and pruning) these sets.
  hiddenCalendars?: string[]
  archivedCalendars?: string[]
}) {
  // A STABLE guard, so it can sit in an effect's dependency list honestly
  // instead of behind an eslint-disable. `makeGuard(onExpire)` written at the
  // top of a render mints a fresh function on every paint, which would re-run
  // every effect that named it. Same shape (and same reason) as DataProvider.
  const expire = useRef(onExpire)
  expire.current = onExpire
  const guard = useMemo(() => makeGuard(() => expire.current()), [])

  const tf = useTimeFormat()
  const { lists, tasks, loaded, create, toggle } = useTaskData()

  // ── the day, and the rollover that keeps it honest ───────────────────────
  const [day, setDay] = useState(() => ymd(new Date()))
  // Bumped every time the rollover timer fires, purely so the effect below
  // re-runs and arms the next one. It deliberately does NOT key off `day`: when
  // the timer fires and the date has not actually changed, `setDay` writes the
  // value already in state, React bails out of the re-render, the effect never
  // re-runs — and the surface is stuck on that day for the life of the page,
  // which is the exact failure the timer exists to prevent.
  const [armed, setArmed] = useState(0)

  useEffect(() => {
    const now = new Date()
    // Built from the local calendar fields rather than by adding 86_400_000 ms,
    // which is an hour wrong on both changeover days in any zone that observes
    // DST — and this repo's own test suite runs in America/New_York precisely
    // so that class of bug can fail a test.
    const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1).getTime()
    const t = setTimeout(() => {
      // The wall clock decides, never arithmetic on the key we were holding. A
      // laptop asleep through midnight fires this LATE — possibly days late,
      // and browsers throttle background timers besides — so reading the clock
      // lands on the day it actually is now rather than on the day after the
      // one it used to be.
      setDay(ymd(new Date()))
      setArmed((n) => n + 1)
    }, Math.max(0, next - now.getTime()) + MIDNIGHT_SLACK_MS)
    return () => clearTimeout(t)
  }, [armed])

  // ── the plan ─────────────────────────────────────────────────────────────
  const [plan, setPlan] = useState<DayPlan | null>(null)
  // Every fetch is stamped and every write bumps the stamp, so a response
  // commits only while it is still the newest — the same guard `useTaskData`
  // puts on its task fetches. It matters more here than it looks: each write
  // this view makes publishes `day_updated`, which bumps `rev` a beat later and
  // re-runs the effect below, so without the stamp a refetch would routinely
  // land on top of the optimistic paint that provoked it and undo it for a
  // frame. It is also what drops a response for a day that has since rolled
  // over — the rollover re-runs this effect, which bumps the stamp.
  const token = useRef(0)

  useEffect(() => {
    const mine = ++token.current
    void guard(async () => {
      const p = await api.openDay(day)
      if (mine !== token.current) return
      // A malformed body must not become the array every render maps over —
      // `guard` shields us from a rejection, not from a 200 with junk in it.
      if (p && Array.isArray(p.entries)) setPlan(p)
    })
  }, [day, rev, guard])

  // Keyed on the day it was fetched for, so a rollover shows NOTHING rather
  // than yesterday's rows under today's heading — the rows on screen and the
  // day every write carries have to be the same day or the surface lies.
  // `null` means "not known yet", which is what keeps the empty state from
  // flashing before the first open lands. Dropped entries come back on every
  // read by design (the server stamps rather than deletes, so a past day can
  // still say what was declined) and are filtered here, the one place with a
  // reason to.
  const entries = useMemo(
    () => (plan && plan.day === day
      ? orderEntries(plan.entries.filter((e) => !e.dropped_at))
      : null),
    [plan, day])

  /** Replace one entry of the plan in hand, by id.
   *
   *  A no-op once the plan has been replaced by another day's — entry ids are
   *  uuid4 hex, so a stale write cannot collide with a row of the new day. */
  const patchEntry = useCallback((entryId: string, patch: Partial<DayEntry>) => {
    setPlan((p) => (p
      ? { ...p, entries: p.entries.map((e) => (e.entry_id === entryId ? { ...e, ...patch } : e)) }
      : p))
  }, [])

  /**
   * Swap the server's row in for the one painted optimistically under `localId`.
   *
   * The add is idempotent three ways — same entry_id, same task, or same note
   * text on the same day — so the row that comes back may be one that was
   * ALREADY on the day under a DIFFERENT entry_id. Collapsing both onto the DTO
   * rather than mapping each to it is what stops two identical rows fighting
   * over one React key. Appending is gated on the day still matching, so a
   * response that lands after midnight cannot resurrect an entry onto a day it
   * does not belong to.
   */
  const settleEntry = useCallback((localId: string, dto: DayEntry) => {
    setPlan((p) => {
      if (!p) return p
      let placed = false
      const next: DayEntry[] = []
      for (const e of p.entries) {
        if (e.entry_id !== localId && e.entry_id !== dto.entry_id) { next.push(e); continue }
        if (placed) continue
        placed = true
        next.push(dto)
      }
      if (!placed && p.day === dto.day) next.push(dto)
      return { ...p, entries: next }
    })
  }, [])

  const dropLocal = useCallback((entryId: string) => {
    setPlan((p) => (p ? { ...p, entries: p.entries.filter((e) => e.entry_id !== entryId) } : p))
  }, [])

  /** Tick or un-tick a NOTE. A task row never reaches this — see the header. */
  const toggleNote = useCallback(async (e: DayEntry) => {
    const done = !e.done_at
    token.current += 1
    // A local stand-in for the instant between the click and the reply; the
    // server's own stamp is what the row settles on below.
    patchEntry(e.entry_id, { done_at: done ? new Date().toISOString() : null })
    const dto = await guard(() => api.patchDayEntry(day, e.entry_id, { done }))
    // Put the old stamp back on failure rather than leaving the UI claiming a
    // tick that never landed — `guard` has already raised the toast.
    patchEntry(e.entry_id, dto ?? { done_at: e.done_at })
  }, [day, guard, patchEntry])

  /** Take a row off the day. Every row can be dropped, task or note alike. */
  const drop = useCallback(async (e: DayEntry) => {
    token.current += 1
    dropLocal(e.entry_id)
    const dto = await guard(() => api.patchDayEntry(day, e.entry_id, { dropped: true }))
    // A failed drop has to come BACK, in its old place — the sort key is the
    // row's own (position, created_at, entry_id), so restoring the entry
    // unchanged puts it exactly where it was.
    if (!dto) setPlan((p) => (p && p.day === e.day ? { ...p, entries: [...p.entries, e] } : p))
  }, [day, guard, dropLocal])

  /**
   * Put a task on `on`. Returns whether it landed.
   *
   * `on` is passed rather than read from `day` inside the awaits: a line typed
   * at 23:59:59 belongs to the day it was typed on, and the rollover timer may
   * fire while this is in flight.
   */
  const addTask = useCallback(async (on: string, t: Task): Promise<boolean> => {
    token.current += 1
    const entry_id = clientId()
    // Painted before the round trip, carrying the id the server will store it
    // under, so a retry lands on this row rather than beside it. `position` is
    // null because the server assigns it (max + 1) — and `orderEntries` sorts
    // an unpositioned row to the END, which is exactly where the server is
    // about to put it, so the row does not move when the DTO arrives.
    const optimistic: DayEntry = {
      entry_id, day: on, kind: 'task', list: t.list, uid: t.uid, title: null,
      source: 'user', position: null, done_at: null, dropped_at: null,
      created_at: new Date().toISOString(),
    }
    setPlan((p) => (p && p.day === on
      // `planned` too — but note what that does and does not mean. Adding a row
      // makes the day report planned, because a plan holding a row while still
      // claiming planned=false would contradict itself. It does NOT open the
      // day: the snapshot marker stays unset, so a later open still derives the
      // due-today, overdue and carried rows around what was hand-added.
      ? { ...p, planned: true, entries: [...p.entries, optimistic] }
      : p))
    const dto = await guard(
      () => api.addDayEntry(on, { entry_id, kind: 'task', list: t.list, uid: t.uid }))
    if (!dto) { dropLocal(entry_id); return false }
    settleEntry(entry_id, dto)
    return true
  }, [guard, settleEntry, dropLocal])

  /** Put a note on `on`. Same optimistic shape as `addTask`. */
  const addNote = useCallback(async (on: string, title: string): Promise<boolean> => {
    token.current += 1
    const entry_id = clientId()
    const optimistic: DayEntry = {
      entry_id, day: on, kind: 'note', list: null, uid: null, title,
      source: 'user', position: null, done_at: null, dropped_at: null,
      created_at: new Date().toISOString(),
    }
    setPlan((p) => (p && p.day === on
      ? { ...p, planned: true, entries: [...p.entries, optimistic] }
      : p))
    const dto = await guard(() => api.addDayEntry(on, { entry_id, kind: 'note', title }))
    if (!dto) { dropLocal(entry_id); return false }
    settleEntry(entry_id, dto)
    return true
  }, [guard, settleEntry, dropLocal])

  // ── the add box ──────────────────────────────────────────────────────────
  const [text, setText] = useState('')
  // The reading was declined for the line as it stands. Cleared on the next
  // keystroke because `parseEntry` reads the WHOLE line — one more character
  // can change or withdraw the reading, so the thing that was declined no
  // longer exists to stay declined.
  const [declined, setDeclined] = useState(false)
  // Re-read on every keystroke, which is what makes the chip a live preview
  // rather than something the user has to ask for. `day` is in the deps for the
  // same reason it is in the window's: `parseEntry` resolves "tomorrow" and
  // "friday" against the clock it is handed, so a line left sitting in the box
  // across midnight has to be read again or the chip would promise a date one
  // day behind the one the entry would actually get.
  const parsed = useMemo(() => parseEntry(text, new Date()), [text, day])
  const reads = !!(parsed.dueDate || parsed.dueTime)
  const showChip = reads && !declined

  const commit = async () => {
    const raw = text.trim()
    if (!raw) return
    // Cleared first: the box has to be ready for the next line before the round
    // trip finishes, which is the whole bargain of a frictionless add. The text
    // goes back on failure (as the dashboard's quick add does), so a rejected
    // line is never simply lost.
    setText('')
    setDeclined(false)
    const on = day
    // A parsed date or time authors a REAL TASK — something with a due date
    // belongs on a list where the rest of the account can see it, and the day
    // entry then points at it. Everything else is a note, which lives only in
    // the day.
    //
    // A line that parsed but has nowhere to go — a brand-new account, or the
    // lists fetch still in flight — falls back to a note carrying the LITERAL
    // text, not `parsed.summary`: the parser DELETES the phrase it recognised,
    // and a note that quietly lost its "at 7" is the silent loss daytext.ts's
    // own header is written to avoid.
    const listId = lists[0]?.id
    const ok = showChip && listId
      ? await addParsedTask(on, listId, parsed)
      : await addNote(on, raw)
    if (!ok) setText(raw)
  }

  const addParsedTask = async (on: string, listId: string, p: ParsedEntry): Promise<boolean> => {
    // The first list in sidebar order. The box is deliberately ONE input — a
    // list picker beside it is the friction this surface exists to remove — and
    // the task is editable in the Tasks pane the moment it exists.
    const t = await create(listId, { summary: p.summary, due: dueFromParse(p, on) })
    if (!t) return false                 // `create` has already raised the toast
    return addTask(on, t)
  }

  // ── suggestions: tasks ───────────────────────────────────────────────────
  // (list, uid) is a task's identity everywhere in this app — a UID is unique
  // per COLLECTION, not per account (see order.ts and the backend's invariant
  // #4) — so a day entry is joined back to its task on BOTH halves. Matching on
  // the uid alone would tick the wrong copy of a task that has been copied
  // between lists in Tasks.org or Thunderbird.
  const taskFor = useCallback(
    (e: DayEntry) => (e.uid ? tasks.find((t) => t.uid === e.uid && t.list === e.list) : undefined),
    [tasks])

  // What the day already holds, keyed the way `sortTasks` keys a task, so the
  // suggestion lists cannot offer something that is already on screen above
  // them. Built by resolving each entry to its task rather than by rebuilding
  // `taskKey`'s string here, so the two can never drift apart.
  //
  // Dropped entries are already gone from `entries`, and that is deliberate:
  // having dropped something this morning, choosing it again this afternoon has
  // to work — the server's add is idempotent EXCEPT over dropped rows for
  // exactly that reason.
  const onDay = useMemo(() => {
    const s = new Set<string>()
    for (const e of entries ?? []) {
      if (e.kind !== 'task') continue
      const t = taskFor(e)
      if (t) s.add(taskKey(t))
    }
    return s
  }, [entries, taskFor])

  const suggestions = useMemo(() => {
    // Top-level only, matching the snapshot the backend builds: a checklist
    // item is not a separate thing to plan, and admitting subtasks would let
    // one parent task drag twenty rows onto the day (service.py's
    // `_snapshot_for` skips anything with a `related_parent` for that reason).
    const open = tasks.filter((t) => !t.parent && !t.completed && !t.cancelled)
    const free = open.filter((t) => !onDay.has(taskKey(t)))
    // Measured from the day on screen, not from `new Date()`: after a rollover
    // the horizon has to move with the day, and the two are the same value on
    // every other render anyway.
    const soon = ymd(addDays(new Date(`${day}T00:00`), SOON_DAYS))
    const dueToday = free.filter((t) => t.due && dayKey(t.due) === day)
    // Disjoint from the bucket above, by key. A task due at 09:00 today is
    // BOTH `dayKey(due) === today` and `isOverdue` from 09:01, and one task
    // offered twice is two "add" buttons for one row — the first press makes
    // the second a no-op the user cannot explain.
    const todayKeys = new Set(dueToday.map(taskKey))
    return [
      { key: 'today', label: 'Due today', items: sortTasks(dueToday) },
      {
        key: 'overdue',
        label: 'Overdue',
        items: sortTasks(free.filter(
          (t) => isOverdue(t.due, t.due_is_date) && !todayKeys.has(taskKey(t)))),
      },
      {
        key: 'soon',
        label: 'Next seven days',
        items: sortTasks(free.filter(
          (t) => t.due && dayKey(t.due) > day && dayKey(t.due) <= soon)),
      },
    ].filter((g) => g.items.length > 0)
  }, [tasks, onDay, day])

  // Through `cssColor` at the accessor, so every downstream style site is
  // covered: these values are whatever another CalDAV client wrote into the
  // collection's calendar-color, and they land in inline styles — see util.ts.
  const colorOf = useCallback(
    (listId: string | null) => cssColor(lists.find((l) => l.id === listId)?.color), [lists])

  // ── the calendar strip ───────────────────────────────────────────────────
  const { cals, loaded: calsLoaded, eventsFor, requestWindow, windowErrors } = useCalendarData()
  const archived = useMemo(() => new Set(archivedCalendars), [archivedCalendars])
  const hidden = useMemo(() => new Set(hiddenCalendars), [hiddenCalendars])

  // The Home dashboard's window, expression for expression (HomeView.tsx ~120):
  // the six-week grid around the current month, `to` exclusive. Sharing the
  // EXPRESSION is what makes the two views share the FETCH — `requestWindow`
  // dedupes on (from, to, rev, calendar ids), so a window differing by one day
  // would fan out over every calendar a second time and repoint the provider's
  // single-slot `latest`/`seeded` refs at it, which is how the disk mirror ends
  // up holding a window nothing reads.
  //
  // Keyed on `day` rather than `rev`: this view's clock is the day key, and a
  // rollover into a new month has to move the grid. Both views still spell
  // `monthGrid(new Date())`, so on any render they name the same window.
  const days = useMemo(() => monthGrid(new Date()), [day])
  const from = ymd(days[0])
  const to = ymd(addDays(days[41], 1))
  // Archived calendars are dropped before the fetch, merely hidden ones are
  // filtered at render — the same split HomeView and CalendarView make. It has
  // to be the same split here, or the calendar SET differs and the shared
  // window is lost along with it.
  const wanted = useMemo(() => cals.filter((c) => !archived.has(c.id)), [cals, archived])

  useEffect(() => {
    requestWindow(from, to, wanted)
    // eslint-disable-next-line react-hooks/exhaustive-deps
    // `requestWindow`, deliberately, and NOT `rev`. It is a useCallback over
    // [rev, enabled, fetchWindow], so its identity already carries the SSE bump
    // — naming `rev` beside it would be a second source of truth for one
    // signal, and the dep array would still be lying about what the effect
    // reads. See the same note at HomeView.tsx ~146. Deduping is unaffected:
    // `requestWindow` stamps `asked` with `rev`, so a re-run within one rev is
    // a no-op.
  }, [from, to, wanted.map((c) => c.id).join(','), requestWindow])

  // `fetchWindow` uses `allSettled`, so one calendar answering 502 never
  // rejects, never reaches `makeGuard`'s catch, and never raises the error
  // toast — the day would simply be short of events with nothing to say so. A
  // confidently short day is worse than a visibly broken one, so the failures
  // are read back by name and rendered. Same banner, same words, as HomeView.
  const calErrors = windowErrors(from, to)
  const events = eventsFor(from, to)

  // An event carries its collection href, not a calendar id — that is what maps
  // it back to the calendar whose colour it should wear, and to the id the
  // hidden set is written in.
  const calByHref = useMemo(() => new Map(cals.map((c) => [c.href, c] as const)), [cals])
  const todaysEvents = useMemo(() => {
    const visible = events.filter((e) => !hidden.has(calByHref.get(e.calendar)?.id || ''))
    // Through the shared bucketer rather than a local `start` filter: a span is
    // listed on every day it covers and continuation days are marked `cont`,
    // which is what `AgendaEvent` reads to label a mid-week day of a long event
    // correctly. A one-day filter would drop a three-day conference on days two
    // and three.
    return bucketByDay(visible, days).get(day) ?? []
  }, [events, hidden, calByHref, days, day])

  const eventStyle = useCallback((e: CalEvent): CSSProperties | undefined => {
    const c = cssColor(calByHref.get(e.calendar)?.color)
    return c ? { '--ev-c': c } as CSSProperties : undefined
  }, [calByHref])

  const heading = new Date(`${day}T00:00`).toLocaleDateString(undefined,
    { weekday: 'long', month: 'long', day: 'numeric' })
  const openCount = (entries ?? []).filter(
    (e) => (e.kind === 'task' ? !taskFor(e)?.completed : !e.done_at)).length

  return (
    <div className="content">
      <div className="content-head">
        <span className="content-title">Today</span>
        <span className="content-sub">{heading}</span>
        <span className="spacer" />
        {entries !== null && (
          <span className="content-sub">
            {openCount} open · {entries.length} on the day
          </span>
        )}
      </div>

      {calErrors.length > 0 && (
        <div className="cal-partial" role="status">
          Couldn&rsquo;t load {calErrors.join(', ')} &mdash; some events may be missing.
        </div>
      )}

      <form className="quickadd today-add"
        onSubmit={(e) => { e.preventDefault(); void commit() }}>
        <input className="input" value={text} aria-label="Add to today"
          placeholder="Add to today — “invoice friday”, “gym at 7”…"
          onChange={(e) => { setText(e.target.value); setDeclined(false) }} />
        <button className="btn" type="submit" disabled={!text.trim()}>Add</button>
        {showChip && (
          // Advisory, never a gate: Enter commits whether or not this has been
          // looked at, which is the difference between a preview and a
          // confirmation step. The date and time are rendered through `fmtDue`
          // with the live 12/24-hour setting, so what the chip promises is
          // exactly what the row will read once it exists.
          <p className="today-chip" role="status">
            <span className="label">{parsed.guessed ? 'reading (guess)' : 'reading'}</span>
            <span className="today-chip-sum" dir={textDir(parsed.summary)}>{parsed.summary}</span>
            <span className="mono">
              {fmtDue(dueFromParse(parsed, day), !parsed.dueTime, tf)}
            </span>
            <button type="button" className="chip-x" onClick={() => setDeclined(true)}
              aria-label="Add the line as typed instead">✕</button>
          </p>
        )}
      </form>

      <div className="scroll">
        {entries !== null && entries.length === 0 && (
          <p className="empty">
            Nothing on today yet. Type a line above, or add one of the tasks below.
          </p>
        )}
        {entries !== null && entries.length > 0 && (
          <ul className="today-list">
            {entries.map((e) => (
              <TodayRow key={e.entry_id} entry={e} task={taskFor(e)} tasksLoaded={loaded}
                color={colorOf(e.list)} onToggleTask={toggle} onToggleNote={toggleNote}
                onDrop={drop} />
            ))}
          </ul>
        )}

        <div className="label section-label">On the calendar</div>
        <CalendarStrip events={todaysEvents} day={day} loaded={calsLoaded}
          styleOf={eventStyle} />

        {suggestions.map((g) => (
          <section key={g.key}>
            <div className="label section-label">{g.label}</div>
            <ul className="today-list">
              {g.items.map((t) => (
                <li key={taskKey(t)} className="today-row today-sug">
                  <button type="button" className="today-plus"
                    aria-label={`Add ${t.summary || '(untitled)'} to today`}
                    onClick={() => void addTask(day, t)}>+</button>
                  <span className="list-dot" style={colorOf(t.list)
                    ? { background: colorOf(t.list)! } : undefined} />
                  <span className="today-title" dir={textDir(t.summary)}>
                    {t.summary || '(untitled)'}
                  </span>
                  {t.due && (
                    <span className={`today-due mono ${g.key === 'overdue' ? 'overdue' : ''}`}>
                      {fmtDue(t.due, t.due_is_date, tf)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  )
}

/** Today's events, read-only.
 *
 *  An event is already committed time: it is context for planning the day, not
 *  a thing to plan, so it never becomes a `day_plan` entry and there is no way
 *  to add one from here. `AgendaEvent` with no `onOpen` is what makes the row
 *  static — the same lever the Home mini-calendar pulls — so this surface
 *  cannot grow an event editor by accident. */
function CalendarStrip({ events, day, loaded, styleOf }: {
  events: DayEv[]
  day: string
  /** The calendars fetch has come back at least once. */
  loaded: boolean
  styleOf: (e: CalEvent) => CSSProperties | undefined
}) {
  // `eventsFor` answers `[]` both for "no events" and for "nothing known yet",
  // so length alone cannot tell them apart — and "Nothing on the calendar
  // today" flashing up before a busy day paints reads as a bug, exactly as it
  // does in the dashboard's TaskList. `loaded` is the calendars fetch, one hop
  // ahead of the events, and the only "it landed" signal this provider exposes;
  // it does not prove the events for THIS window have arrived, so this is a
  // floor on the claim rather than a guarantee. Staying blank is the safe side
  // of that: it asserts nothing.
  if (!loaded && !events.length) return null
  if (!events.length) return <p className="empty today-quiet">Nothing on the calendar today.</p>
  return (
    <div className="today-agenda">
      {events.map((ev) => (
        <AgendaEvent key={eventKey(ev)} ev={ev} day={day} style={styleOf(ev)} />
      ))}
    </div>
  )
}

function TodayRow({ entry, task, tasksLoaded, color, onToggleTask, onToggleNote, onDrop }: {
  entry: DayEntry
  /** The task a task entry points at, once it is in hand. */
  task: Task | undefined
  /** The tasks fetch has come back at least once this session. */
  tasksLoaded: boolean
  color: string | null
  onToggleTask: (t: Task) => Promise<void>
  onToggleNote: (e: DayEntry) => Promise<void>
  onDrop: (e: DayEntry) => Promise<void>
}) {
  const tf = useTimeFormat()
  const isTask = entry.kind === 'task'
  // The task a row points at can genuinely go away — deleted in another CalDAV
  // client, or its whole list removed — and the entry survives it, because
  // `day_plan` carries no foreign key on purpose: what a day recorded should
  // not vanish because the task did. Saying so beats a blank row. But only once
  // the tasks have actually landed: before that, "gone" would be a confident
  // claim about a fetch still in flight, so the row waits with an empty title
  // instead. `tasksLoaded` is `useTaskData().loaded`, the same gate the
  // dashboard's TaskList uses.
  const gone = isTask && !task && tasksLoaded
  const title = !isTask
    ? entry.title || ''
    : task ? (task.summary || '(untitled)')
      : gone ? 'This task is no longer in your lists' : ''
  const done = isTask ? !!task?.completed : !!entry.done_at

  return (
    <li className={`today-row ${done ? 'done' : ''} ${gone ? 'gone' : ''}`}>
      {/* Nothing to tick when the task is gone: the checkbox writes a VTODO
          STATUS, and there is no VTODO. The drop control still works, which is
          how the row is cleared off the day. */}
      {gone ? <span className="today-check-gap" aria-hidden="true" /> : (
        <button type="button" className={`check ${done ? 'on' : ''}`}
          // The task's own state, and its own writer. A task entry never
          // records doneness of its own — see this file's header.
          disabled={isTask && !task}
          aria-pressed={done}
          aria-label={`${done ? 'Uncheck' : 'Check'} ${title || 'entry'}`}
          onClick={() => void (isTask && task ? onToggleTask(task) : onToggleNote(entry))}>
          ✓
        </button>
      )}
      {isTask && (
        <span className="list-dot" style={color ? { background: color } : undefined} />
      )}
      <span className="today-title" dir={textDir(title)}>{title}</span>
      {task?.due && (
        <span className="today-due mono">{fmtDue(task.due, task.due_is_date, tf)}</span>
      )}
      <button type="button" className="today-drop"
        aria-label={`Remove ${title || 'entry'} from today`}
        onClick={() => void onDrop(entry)}>✕</button>
    </li>
  )
}
