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
//     exists nowhere but in the day. That one is a PATCH. A HABIT OCCURRENCE is
//     on this side of the fence too, for exactly the same reason — see below.
//
// ── habits ─────────────────────────────────────────────────────────────────
//
// A habit is A RULE THAT INSERTS ENTRIES. Opening a day gives it one ordinary
// `day_plan` row per active habit due that weekday, and that row is the whole
// of it: there is no second ledger, no per-habit history table, nothing on the
// wire. So a habit occurrence ticks like a note (its own `done_at`, a PATCH),
// drops like anything else, and is ordered by the same key.
//
// What it does NOT do is mix in. Habits paint in their own group above the rest
// of the day — a RENDER-LEVEL partition over the same ordered array, not a
// second ordering — because they are the repeating spine of the day rather than
// today's news, and a habit sitting between two one-off jots reads as a jot.
// They are also absent from the suggestions below: a habit is scheduled, and
// offering to add something that is already coming back tomorrow is offering
// the owner a decision they have already made. (That one holds by construction
// — suggestions are drawn from `tasks`, and a habit is never a task — so the
// test that pins it is guarding the property, not a branch.)
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
import {
  api, clientId, HABIT_DAYS,
  type CalEvent, type DayEntry, type DayPlan, type Habit, type PatchHabitBody, type Task,
} from '../api'
import { useCalendarData, useTaskData } from '../data'
import { useEscape } from '../hooks'
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

/** The smallest denominator the weekly count is willing to be shown at.
 *
 *  With one occurrence there is nothing to say: "0 of 1 this week" on a Monday
 *  morning is a scoreboard opened on the first play, and "1 of 1" is a
 *  congratulation for getting out of bed. Two is the smallest number that
 *  describes a habit rather than a single day, so below it the count is omitted
 *  ENTIRELY rather than shown as an empty or zeroed one. */
const MIN_WEEK_COUNT = 2

/**
 * The Monday of the week the day key `day` falls in, as a day key.
 *
 * THE ONE PLACE the two week conventions in play are converted between, which
 * is why it is a named function rather than an expression inline at its single
 * call site. `Date.getDay()` is 0=SUNDAY. Everything else in reach is
 * Monday-first: a habit's `days` is written mon..sun (`HABIT_DAYS`), the server
 * derives a weekday with Python's `date.weekday()` (0=Monday), and the booking
 * availability map has keyed "0" to Monday since long before habits existed.
 * `(getDay() + 6) % 7` is that shift — Sunday's 0 becomes 6, Monday's 1 becomes
 * 0 — and it is used for exactly one thing: finding where the week the count
 * spans begins.
 *
 * It deliberately does NOT go the other way. Turning a weekday number back into
 * one of the `HABIT_DAYS` names would be a second copy of the mapping the
 * server already owns, and which day a habit runs on is the server's decision
 * (taken off the day key's own characters, so no clock and no zone is involved).
 * Two copies of that mapping is how "wed" comes to mean Wednesday on one side
 * and Thursday on the other, for one weekday only, silently.
 *
 * The key is parsed as LOCAL midnight — the same `${day}T00:00` spelling the
 * suggestion horizon uses below — because a bare "2026-08-21" parses as UTC and
 * lands on the previous day for every viewer west of it.
 */
export function weekStartOf(day: string): string {
  const d = new Date(`${day}T00:00`)
  return ymd(addDays(d, -((d.getDay() + 6) % 7)))
}

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

  // A RENDER-LEVEL partition over the array `orderEntries` already ordered —
  // both halves keep the positions the server gave them, and nothing is sorted
  // a second time.
  //
  // The split is doing real work rather than confirming an order that is already
  // there. Habits lead the FIRST snapshot of a day and nothing else: a habit
  // created at 18:00 is topped up onto the END of a day the owner has spent all
  // day arranging (`service.open_day` — a late arrival must not renumber the
  // arrangement it is joining), so without this it would appear under the last
  // thing they typed rather than with the rest of the spine.
  const habitRows = useMemo(() => entries?.filter((e) => e.kind === 'habit') ?? [], [entries])
  // `!== 'habit'` rather than a list of the other two: a kind this build has
  // never heard of belongs with the day's ordinary rows, where it is at worst
  // in the wrong order, rather than silently vanishing off the screen.
  const dayRows = useMemo(() => entries?.filter((e) => e.kind !== 'habit') ?? [], [entries])

  // ── the week behind each habit's count ───────────────────────────────────
  //
  // ONE read feeds every habit on the screen. `api.days` answers a whole span
  // in a single call — a `DayPlan[]` holding the days in it that have a plan,
  // which `habitWeek` below keys by day for itself — so a count per habit would
  // be the same information fetched N times; and it is `api.days`, never
  // `openDay`, because reading a week must not OPEN six days — that would fill
  // the record with plans the owner never made, each frozen at whatever
  // happened to be due at prefetch time.
  //
  // Monday to today inclusive. `to` is EXCLUSIVE, hence tomorrow. The week
  // starts on Monday to match the vocabulary a habit's `days` is written in; a
  // Sunday-first week would put the same Sunday in two different weeks
  // depending on which side of the app you asked.
  //
  // Stored WITH the day it was fetched for, for the same reason `plan` carries
  // its own `day`: both ends of the range move at a rollover, and until the
  // refetch lands the plans in hand are the ones the previous range answered.
  // See the guard in `habitWeek`.
  const [week, setWeek] = useState<{ day: string; plans: DayPlan[] } | null>(null)
  const weekToken = useRef(0)
  const weekStart = weekStartOf(day)
  const weekEnd = ymd(addDays(new Date(`${day}T00:00`), 1))

  useEffect(() => {
    const mine = ++weekToken.current
    void guard(async () => {
      const ps = await api.days(weekStart, weekEnd)
      if (mine !== weekToken.current) return
      if (Array.isArray(ps)) setWeek({ day, plans: ps })
    })
    // `day` alongside the two ends it derives: both are pure functions of it,
    // so naming it adds no re-runs, and it is what the response is stamped with.
  }, [day, weekStart, weekEnd, rev, guard])

  /**
   * Per habit id, this week so far: how many occurrences were ticked, out of how
   * many EXIST.
   *
   * The denominator is what makes the number honest, and it is deliberately not
   * the count of scheduled weekdays. An absent row conflates three different
   * facts: the habit was not scheduled that day, it was scheduled and missed, or
   * THE APP WAS NEVER OPENED THAT DAY. Only the middle one is a miss, and after
   * the fact nothing can tell them apart — a day nobody opened has no plan, so
   * it has no rows either way, and the habit that "should" have run on it never
   * did. Counting scheduled weekdays would quietly charge the owner for the days
   * they were on holiday, ill, or simply not at a screen, which is the single
   * most demoralising thing a habit tracker does.
   *
   * So the count is over the occurrences that exist: of the days this habit
   * actually came up, how many were done.
   *
   * Dropped occurrences leave BOTH halves. "I decided not to do this" is a
   * decision the day recorded, not a failure to act on one, so counting it as a
   * miss would be the same lie pointing the other way.
   */
  const habitWeek = useMemo(() => {
    const byDay = new Map<string, DayEntry[]>()
    // Keyed to the day it was fetched for, exactly as `entries` is: a Sunday to
    // Monday rollover moves BOTH ends of the range, and until the refetch lands
    // the plans in hand are last week's. Counting them under this week's
    // heading would say "5 of 7 this week" about a week that has ended, which
    // is the staleness this file refuses everywhere else — showing nothing is
    // the honest answer while the surface does not know yet.
    for (const p of (week && week.day === day ? week.plans : [])) {
      if (p && Array.isArray(p.entries)) byDay.set(p.day, p.entries)
    }
    // Today comes from the plan in hand, REPLACING the range read's copy of it
    // rather than adding to it — the range covers today too, and counting the
    // day twice would double every habit's numbers. The local copy is the one
    // that has already absorbed the optimistic tick, so the count moves on the
    // click rather than a round trip later.
    if (entries) byDay.set(day, entries)
    const out = new Map<string, { done: number; total: number }>()
    for (const rows of byDay.values()) {
      for (const e of rows) {
        if (e.kind !== 'habit' || !e.habit_id || e.dropped_at) continue
        const c = out.get(e.habit_id) ?? { done: 0, total: 0 }
        c.total += 1
        if (e.done_at) c.done += 1
        out.set(e.habit_id, c)
      }
    }
    return out
  }, [week, entries, day])

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

  /** Tick or un-tick an entry whose doneness lives ON THE ENTRY: a note, or a
   *  habit occurrence. A task row never reaches this — see the header.
   *
   *  Named for the property rather than for the kind because there are two
   *  kinds in it now. The backend permits `done` on both for the same reason it
   *  refuses it on a task: a note and a habit occurrence exist nowhere but in
   *  the day, so the day is the only place their doneness can live. (Ticking a
   *  habit occurrence says the owner did it TODAY. It says nothing about the
   *  rule, which is not a thing that can be completed.) */
  const toggleEntry = useCallback(async (e: DayEntry) => {
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
      // `habit_id` is null on everything a client can add: an occurrence is
      // minted by its rule when a day is opened, never posted from here.
      source: 'user', position: null, done_at: null, dropped_at: null, habit_id: null,
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
      source: 'user', position: null, done_at: null, dropped_at: null, habit_id: null,
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
  //
  // The `kind !== 'task'` skip below already covered habit occurrences the day
  // `kind` widened, and covers them for the right reason rather than by luck: a
  // habit carries no (list, uid) at all, so it names no task and can exclude
  // none from the suggestions. Spelling it `=== 'note'` would have been the
  // same behaviour written as a claim that stops being true on the next kind.
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
  // Habits are counted here, in both halves. They fall down the `!e.done_at`
  // arm of the ternary, which is the right answer for them for the same reason
  // it is for a note — a habit occurrence's doneness is the entry's own — so
  // the widened `kind` needed no branch, only checking. And they belong in the
  // totals: they are on the day, they are on the screen, and a "7 on the day"
  // that disagreed with the number of rows under it would be the one figure
  // here nobody could reconcile.
  const openCount = (entries ?? []).filter(
    (e) => (e.kind === 'task' ? !taskFor(e)?.completed : !e.done_at)).length

  // The habits sheet edits RULES, so it is not part of any one day and does not
  // live in the day's state. It is opened from the header of the tab the habits
  // actually show up on rather than from Settings: the moment you want to change
  // one is the morning you are looking at it.
  const [sheet, setSheet] = useState(false)

  /** One row of the day, whichever group it is painting in. Both lists render
   *  through this so a fix to a row cannot reach one group and miss the other. */
  const renderRow = (e: DayEntry) => (
    <TodayRow key={e.entry_id} entry={e} task={taskFor(e)} tasksLoaded={loaded}
      color={colorOf(e.list)} onToggleTask={toggle} onToggleEntry={toggleEntry}
      onDrop={drop}
      // `kind` as well as `habit_id`, so "undefined on every other kind" is a
      // fact rather than a consequence of the column being null on them today.
      count={e.kind === 'habit' && e.habit_id ? habitWeek.get(e.habit_id) : undefined} />
  )

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
        <button type="button" className="icon-btn today-habits-open"
          aria-haspopup="dialog" aria-label="Habits" title="Habits"
          onClick={() => setSheet(true)}>↻</button>
      </div>

      {sheet && <HabitsSheet rev={rev} guard={guard} onClose={() => setSheet(false)} />}

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
        {/* Habits first, above the day rather than mixed through it. The group
            is skipped entirely when there are none: a heading over nothing
            would advertise a feature as an empty state on every account that
            does not use it. */}
        {habitRows.length > 0 && (
          <section className="today-habits">
            <div className="label section-label">Habits</div>
            {/* Named for assistive tech, which cannot see that the label above
                belongs to this list. It is the one group on this screen whose
                identity is the whole point of it being a group. */}
            <ul className="today-list" aria-label="Habits">
              {habitRows.map(renderRow)}
            </ul>
          </section>
        )}

        {/* Gated on the WHOLE day being empty, not on `dayRows`. A day holding
            three habits and nothing else is not a day with nothing on it, and
            saying so under a visible list of habits would contradict the screen
            it is printed on. */}
        {entries !== null && entries.length === 0 && (
          <p className="empty">
            Nothing on today yet. Type a line above, or add one of the tasks below.
          </p>
        )}
        {dayRows.length > 0 && (
          <ul className="today-list">
            {dayRows.map(renderRow)}
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

function TodayRow({
  entry, task, tasksLoaded, color, count, onToggleTask, onToggleEntry, onDrop,
}: {
  entry: DayEntry
  /** The task a task entry points at, once it is in hand. */
  task: Task | undefined
  /** The tasks fetch has come back at least once this session. */
  tasksLoaded: boolean
  color: string | null
  /** This week's occurrences of the habit this row is one of: how many were
   *  ticked, out of how many EXIST. Undefined on every other kind — and on a
   *  habit whose id nothing counted, which is why the render below asks whether
   *  it is here rather than assuming a habit row always has one. */
  count?: { done: number; total: number }
  onToggleTask: (t: Task) => Promise<void>
  onToggleEntry: (e: DayEntry) => Promise<void>
  onDrop: (e: DayEntry) => Promise<void>
}) {
  const tf = useTimeFormat()
  const isTask = entry.kind === 'task'
  const isHabit = entry.kind === 'habit'
  // The task a row points at can genuinely go away — deleted in another CalDAV
  // client, or its whole list removed — and the entry survives it, because
  // `day_plan` carries no foreign key on purpose: what a day recorded should
  // not vanish because the task did. Saying so beats a blank row. But only once
  // the tasks have actually landed: before that, "gone" would be a confident
  // claim about a fetch still in flight, so the row waits with an empty title
  // instead. `tasksLoaded` is `useTaskData().loaded`, the same gate the
  // dashboard's TaskList uses.
  const gone = isTask && !task && tasksLoaded
  // A habit occurrence takes the `!isTask` arm and reads its OWN title, which is
  // the copy taken from the rule when the row was minted. That is deliberate on
  // both sides: renaming a habit leaves last Tuesday saying what the owner
  // planned last Tuesday, and deleting one leaves the row perfectly readable
  // with nothing left to resolve.
  const title = !isTask
    ? entry.title || ''
    : task ? (task.summary || '(untitled)')
      : gone ? 'This task is no longer in your lists' : ''
  // Same fence as the header describes: a task's doneness is its VTODO's, a
  // note's and a habit occurrence's is the entry's own.
  const done = isTask ? !!task?.completed : !!entry.done_at
  // Assembled rather than interpolated: with a third optional marker the
  // template runs past the line and reads as punctuation.
  const cls = ['today-row', isHabit && 'today-habit', done && 'done', gone && 'gone']
    .filter(Boolean).join(' ')

  return (
    <li className={cls}>
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
          onClick={() => void (isTask && task ? onToggleTask(task) : onToggleEntry(entry))}>
          ✓
        </button>
      )}
      {isTask && (
        <span className="list-dot" style={color ? { background: color } : undefined} />
      )}
      {/* The habit's mark, in the slot a task's list dot occupies, so the two
          kinds of row keep one left edge. Decorative and hidden from assistive
          tech: the list it sits in is already named "Habits", and a screen
          reader announcing "clockwise open circle arrow" before every title is
          noise, not information. */}
      {isHabit && <span className="today-habit-mark mono" aria-hidden="true">↻</span>}
      <span className="today-title" dir={textDir(title)}>{title}</span>
      {/* Omitted ENTIRELY below two occurrences — see MIN_WEEK_COUNT. Rendered
          in --fg-faint whatever the ratio says, and never in --warn: "1 of 5
          this week" is a record, and colouring it as a failure turns the one
          surface the owner opens every morning into something that tells them
          off. */}
      {count && count.total >= MIN_WEEK_COUNT && (
        <span className="today-habit-count mono">
          {count.done} of {count.total} this week
        </span>
      )}
      {task?.due && (
        <span className="today-due mono">{fmtDue(task.due, task.due_is_date, tf)}</span>
      )}
      <button type="button" className="today-drop"
        aria-label={`Remove ${title || 'entry'} from today`}
        onClick={() => void onDrop(entry)}>✕</button>
    </li>
  )
}

// ── the habits sheet ─────────────────────────────────────────────────────────

/** "mon" → "Mon", for a chip's face and for its accessible name.
 *
 *  Display only, and DERIVED from the token rather than looked up in a table
 *  keyed by day. That is the point of writing it this way: any such table —
 *  mapping these seven names to a full day name, and above all to a weekday
 *  NUMBER — would be a second copy of a mapping the server already owns, and
 *  two copies is how "wed" comes to mean Wednesday on one side and Thursday on
 *  the other, for one weekday only. See `HABIT_DAYS` in api.ts. */
const dayLabel = (d: string) => d[0].toUpperCase() + d.slice(1)

/**
 * The days a habit's `days` names, as a set of `HABIT_DAYS` tokens.
 *
 * '' is every day, and the chips show that as ALL SEVEN LIT rather than as none
 * of them. A row of chips is read as "these are the days it comes up", so seven
 * dark chips beside the words "every day" would say the opposite of what they
 * mean.
 */
const daysOn = (days: string): Set<string> =>
  new Set<string>(days ? days.split(',') : HABIT_DAYS)

/**
 * A habit as the PATCH body it was given would leave it, for the paint between
 * the click and the reply.
 *
 * THE ONE PLACE the wire's shape and the row's are converted between, and the
 * conversion is not the identity: pausing is a BOOLEAN on the body and a STAMP
 * on the row. The stand-in stamp is local, exactly as `toggleEntry`'s `done_at`
 * is, and the server's own is what the row settles on a moment later — nothing
 * reads the value, only whether it is there (`paused` is `!!paused_at`).
 *
 * An omitted field is left alone, which is what the endpoint does with it too.
 * `undefined` is the only test that can tell "not asked about" from "set to
 * false", because `paused: false` is a real value — resuming. See
 * `PatchHabitBody`.
 */
const applyPatch = (h: Habit, body: PatchHabitBody): Habit => ({
  ...h,
  ...(body.title !== undefined ? { title: body.title } : {}),
  ...(body.days !== undefined ? { days: body.days } : {}),
  ...(body.position !== undefined ? { position: body.position } : {}),
  ...(body.paused !== undefined
    ? { paused_at: body.paused ? h.paused_at ?? new Date().toISOString() : null }
    : {}),
})

/**
 * Where habits are made, renamed, rescheduled, paused and deleted.
 *
 * It edits RULES, not a day, so it holds none of the day's state and writes
 * none of it. What it changes reaches the screen behind it the way every other
 * write in this app does: the server publishes `day_updated`, `rev` bumps, and
 * the view re-opens the day — which is also what mints today's occurrence of a
 * habit created this morning, since opening a day tops up the rows its rules are
 * owed. Re-fetching the day from in here as well would be a second path for one
 * signal, and the two would drift.
 *
 * The dialog conventions are the ones every other overlay in this app keeps —
 * `.overlay` + `.modal`, `aria-modal`, a ✕, a scrim that closes on a press AND
 * release that both land on it, and `useEscape` — rather than a set invented for
 * this one screen. The scrim's two-event dance is not fussiness: a bare onClick
 * fires whenever the release lands on the scrim, so a text drag-select that
 * began inside the sheet and finished outside it would discard the whole thing.
 */
function HabitsSheet({ rev, guard, onClose }: {
  rev: number
  guard: ReturnType<typeof makeGuard>
  onClose: () => void
}) {
  const [habits, setHabits] = useState<Habit[] | null>(null)
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  // The same stamp discipline the day plan uses: a fetch commits only while it
  // is still the newest, and every write bumps it. Without it the list refetch
  // an SSE bump provokes would land on top of the row a write has just settled
  // and undo it for a frame.
  const token = useRef(0)

  useEffect(() => {
    const mine = ++token.current
    void guard(async () => {
      const hs = await api.habits()
      if (mine !== token.current) return
      // A 200 carrying junk is not something `guard` protects against — it
      // shields us from a rejection — and this array is mapped over on render.
      if (Array.isArray(hs)) setHabits(hs)
    })
  }, [rev, guard])

  useEscape(onClose)

  /** Replace one habit in the list in hand, or take it out (`next` null). */
  const put = useCallback((id: string, next: Habit | null) => {
    setHabits((hs) => (hs
      ? (next ? hs.map((h) => (h.id === id ? next : h)) : hs.filter((h) => h.id !== id))
      : hs))
  }, [])

  const add = async () => {
    const t = title.trim()
    if (!t || busy) return
    setBusy(true)
    token.current += 1
    const h = await guard(() => api.createHabit({ title: t }))
    setBusy(false)
    // The typed text stays in the box on failure: `guard` has already raised the
    // toast, and clearing the field as well would lose the line along with the
    // habit. Appended, because the server appends too (position = max + 1), so
    // the row does not move when the list is next fetched.
    if (!h) return
    setTitle('')
    setHabits((hs) => [...(hs ?? []), h])
  }

  const patch = useCallback(async (h: Habit, body: PatchHabitBody) => {
    const mine = ++token.current
    // Painted BEFORE the round trip, the way this app's other writes are, and
    // here it is load-bearing rather than cosmetic: the day chips derive the
    // `days` they send from the row on screen, so with the row only replaced on
    // the reply, two clicks in quick succession would BOTH start from the
    // pre-patch schedule and the second would send the first one's change back
    // off — last write wins, and the owner watches Monday come back on.
    put(h.id, applyPatch(h, body))
    const next = await guard(() => api.patchHabit(h.id, body))
    // Only while this is still the newest write on this sheet — the same stamp
    // discipline the fetch above keeps, and needed for the same reason once the
    // paint is optimistic. A reply to the FIRST of two quick clicks carries a
    // row that knows nothing of the second, so settling it here would undo that
    // second click for as long as its own reply took: the same flicker, coming
    // from the other end. What stands in the meantime is the optimistic row,
    // which is what was asked for and (`days` is canonicalised on both sides,
    // and a rename is trimmed before it is sent) what the server has; every
    // write here publishes, so the refetch that follows reconciles it anyway.
    if (mine !== token.current) return
    // The server's row on success; on failure the row exactly as it stood when
    // this write began, which is what makes a rejected rename read as "that did
    // not take" rather than as a change that is on the screen and nowhere else.
    put(h.id, next ?? h)
  }, [guard, put])

  const remove = useCallback(async (h: Habit) => {
    token.current += 1
    // A 204, so `guard` answers `null` on success and `undefined` on failure. A
    // sentinel rather than telling those two apart by value: `null` vs
    // `undefined` is one refactor away from being lost, and losing it here means
    // a failed delete silently taking the habit off the screen.
    let ok = false
    await guard(async () => { await api.deleteHabit(h.id); ok = true })
    if (ok) put(h.id, null)
  }, [guard, put])

  /** Whether the press that started this click landed on the scrim itself. */
  const scrimPress = useRef(false)

  return (
    <div className="overlay"
      onMouseDown={(e) => { scrimPress.current = e.target === e.currentTarget }}
      onClick={(e) => {
        if (e.target === e.currentTarget && scrimPress.current) onClose()
        scrimPress.current = false
      }}>
      <div className="modal habit-sheet" role="dialog" aria-modal="true" aria-label="Habits"
        onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">Habits</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <p className="habit-blurb">
          A habit is a rule that puts a line on your day. It never becomes a task,
          and it never leaves this app.
        </p>
        {habits !== null && habits.length === 0 && (
          <p className="empty habit-empty">No habits yet.</p>
        )}
        {habits !== null && habits.length > 0 && (
          <ul className="habit-list">
            {habits.map((h) => (
              <HabitEditRow key={h.id} habit={h}
                onPatch={(body) => void patch(h, body)} onDelete={() => void remove(h)} />
            ))}
          </ul>
        )}
        <form className="habit-add" onSubmit={(e) => { e.preventDefault(); void add() }}>
          <input className="input" aria-label="New habit" value={title}
            placeholder="Add a habit — “read”, “stretch”…"
            onChange={(e) => setTitle(e.target.value)} />
          <button className="btn" type="submit" disabled={!title.trim() || busy}>Add</button>
        </form>
      </div>
    </div>
  )
}

/** One habit's rule: its name, the days it comes up on, and the two things that
 *  can be done to it that a past day must survive. */
function HabitEditRow({ habit, onPatch, onDelete }: {
  habit: Habit
  onPatch: (body: PatchHabitBody) => void
  onDelete: () => void
}) {
  const [name, setName] = useState(habit.title)
  const [confirming, setConfirming] = useState(false)
  // The draft follows the habit when it changes UNDERNEATH — a rejected rename
  // leaves the old title in place, and an SSE bump refetches the whole list — so
  // a stale draft cannot be committed over a newer value on the next blur.
  useEffect(() => { setName(habit.title) }, [habit.title])

  const paused = !!habit.paused_at
  const on = daysOn(habit.days)

  const rename = () => {
    const t = name.trim()
    // An empty title is a 422 server-side. Snapping back beats raising an error
    // toast at someone who has merely cleared the field to retype it.
    if (!t) { setName(habit.title); return }
    if (t !== habit.title) onPatch({ title: t })
  }

  const toggleDay = (d: string) => {
    const next = new Set(on)
    if (next.has(d)) next.delete(d)
    else next.add(d)
    // The vocabulary has no way to say "no days", and does not need one: the
    // chips are a RESTRICTION, so clearing the last of them clears the
    // restriction. All seven lit is the same schedule as none named, and '' is
    // that schedule's only spelling server-side — sending the seven names would
    // come back normalised to '' and the row would appear to change under the
    // owner. Ordered through HABIT_DAYS for the same reason: mon..sun is what
    // the server canonicalises to, so what we send is what comes back.
    onPatch({
      days: next.size === 0 || next.size === HABIT_DAYS.length
        ? ''
        : HABIT_DAYS.filter((x) => next.has(x)).join(','),
    })
  }

  return (
    <li className={`habit-edit ${paused ? 'paused' : ''}`}>
      <div className="habit-edit-top">
        <input className="input habit-name" value={name}
          aria-label={`Rename ${habit.title}`}
          onChange={(e) => setName(e.target.value)}
          onBlur={rename}
          // Enter commits without leaving the field. There is deliberately no
          // Escape-to-revert here: Escape closes the sheet, as it closes every
          // other dialog in this app, and one control quietly meaning something
          // else is worse than not offering the shortcut at all.
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); rename() } }} />
        <button type="button" className="btn ghost" aria-pressed={paused}
          aria-label={`${paused ? 'Resume' : 'Pause'} ${habit.title}`}
          onClick={() => onPatch({ paused: !paused })}>
          {paused ? 'Resume' : 'Pause'}
        </button>
        {/* Two presses, like every other delete in this app. The accessible name
            moves with the state as well as the label does — otherwise a screen
            reader announces the same "Delete Read" twice and the confirm step is
            invisible to exactly the people it protects most. */}
        <button type="button" className={`btn ghost ${confirming ? 'danger' : ''}`}
          aria-label={confirming ? `Confirm delete ${habit.title}` : `Delete ${habit.title}`}
          onClick={() => (confirming ? onDelete() : setConfirming(true))}>
          {confirming ? 'Really delete?' : 'Delete'}
        </button>
      </div>
      <div className="habit-days">
        {HABIT_DAYS.map((d) => (
          <button key={d} type="button" className={`chip habit-day ${on.has(d) ? 'on' : ''}`}
            aria-pressed={on.has(d)} aria-label={`${dayLabel(d)} for ${habit.title}`}
            onClick={() => toggleDay(d)}>{dayLabel(d)}</button>
        ))}
        {/* Said in words as well as in chips, because "all seven lit" and "every
            day" are the same schedule and only one of them is legible at a
            glance. Gated on the wire value, not on the set: it is true exactly
            when the habit carries no restriction. */}
        {!habit.days && <span className="label habit-every">Every day</span>}
        {paused && <span className="label habit-paused">Paused</span>}
      </div>
      {confirming && (
        <p className="habit-warn" role="status">
          The rule stops coming back. Every day it has already run on keeps the
          line it put there — a past day is a finished record, not a projection of
          today’s rules.
        </p>
      )}
    </li>
  )
}
