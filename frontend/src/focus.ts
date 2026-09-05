// The focus clock: a pomodoro heartbeat the day's rows ride, DERIVED from the
// session the server keeps rather than counted here.
//
// React-free like order.ts and capacity.ts, so the arithmetic that decides what
// the screen says — how many seconds are left, whether the interval is over,
// whether the owner was away, which row is next, whether a capped row has used
// its estimate — can be pinned by tests that never mount anything. FocusView
// ticks once a second and calls in here with `Date.now()`.
//
// THE SERVER'S SESSION IS ANCHORS, NOT COUNTERS (api.ts, FocusSession). Every
// number on the surface is `phase_elapsed_s` plus the clamped time since
// `running_since`, computed from the wall clock at paint time — which is why
// two windows show the same second, why a refresh loses nothing, and why the
// figure a row is credited with can never exceed the phase it was earned in.

import type { DayEntry, FocusPhase, FocusSession, Settings, Task } from './api'
import { orderEntries, rowDone } from './components/TodayView'

export interface FocusSettings {
  interval: number      // minutes
  brk: number
  longBrk: number
  longEvery: number     // 0 = never a long break
  autoContinue: boolean
  capDefault: boolean
  chime: boolean
  notify: boolean
}

/** Mirrors `service.FOCUS_DEFAULTS`, and the two have to agree — for the reason
 *  `fmtDuration` mirrors `fmt_duration`: a surface that painted 25:00 while the
 *  server started a phase of another length would be the app disagreeing with
 *  itself about the one number on the screen. */
export const DEFAULT_FOCUS: FocusSettings = {
  interval: 25, brk: 5, longBrk: 15, longEvery: 4,
  autoContinue: false, capDefault: false, chime: true, notify: false,
}

/** The edge model's bounds (`SettingsPatch`), restated so a hand-edited blob is
 *  clamped on the way in rather than obeyed — a zero-length interval would end
 *  before it began. */
export const FOCUS_BOUNDS: Record<
  'interval' | 'brk' | 'longBrk' | 'longEvery', readonly [number, number]
> = { interval: [1, 180], brk: [1, 60], longBrk: [1, 120], longEvery: [0, 12] }

/** How far past an interval's end the clock may run before the surface treats
 *  the owner as having been AWAY. A tab throttled in the background for a
 *  minute is late; a laptop opened after lunch was not there. Ninety seconds is
 *  generous to the first and irrelevant to the second. */
export const AWAY_GRACE_S = 90

const MINUTES = {
  interval: 'focus_interval_minutes', brk: 'focus_break_minutes',
  longBrk: 'focus_long_break_minutes', longEvery: 'focus_long_break_every',
} as const
const FLAGS = {
  autoContinue: 'focus_auto_continue', capDefault: 'focus_cap_default',
  chime: 'focus_chime', notify: 'focus_notify',
} as const

/** The focus keys of a settings blob, every one present and sane. Treated as
 *  hand-edited like every other value off the wire: an out-of-range number is
 *  clamped, anything else is the default. */
export function sanitizeFocusSettings(s: Settings | null | undefined): FocusSettings {
  const out = { ...DEFAULT_FOCUS }
  if (!s) return out
  const blob = s as Record<string, unknown>
  for (const k of Object.keys(MINUTES) as Array<keyof typeof MINUTES>) {
    const v = blob[MINUTES[k]]
    if (typeof v === 'number' && Number.isFinite(v)) {
      const [lo, hi] = FOCUS_BOUNDS[k]
      out[k] = Math.min(hi, Math.max(lo, Math.round(v)))
    }
  }
  for (const k of Object.keys(FLAGS) as Array<keyof typeof FLAGS>) {
    const v = blob[FLAGS[k]]
    if (typeof v === 'boolean') out[k] = v
  }
  return out
}

export function phaseLengthS(phase: FocusPhase, settings: FocusSettings): number {
  const minutes = phase === 'focus' ? settings.interval
    : phase === 'break' ? settings.brk : settings.longBrk
  return 60 * minutes
}

// ── the clock ──────────────────────────────────────────────────────────────

/** Seconds of the CURRENT run, unclamped: how long the anchor has been set. */
const runS = (s: FocusSession, nowMs: number): number =>
  s.running_since ? Math.max(0, (nowMs - Date.parse(s.running_since)) / 1000) : 0

/** Seconds into the phase, the live run clamped to what the phase has left —
 *  the client-side twin of the server's settle, and the reason the two agree
 *  about every number on the screen. */
export function elapsedIn(s: FocusSession, nowMs: number): number {
  const room = Math.max(0, s.phase_length_s - s.phase_elapsed_s)
  return s.phase_elapsed_s + Math.min(room, Math.floor(runS(s, nowMs)))
}

export interface FocusClock {
  elapsed: number
  remaining: number
  /** The phase has used its whole length. */
  over: boolean
  /** The anchor is set and the phase is not over: the number on screen moves. */
  running: boolean
  /** Not running, not over, not ended: waiting to be resumed. */
  paused: boolean
}

export function clockOf(s: FocusSession, nowMs: number): FocusClock {
  const elapsed = elapsedIn(s, nowMs)
  const over = elapsed >= s.phase_length_s
  const running = !!s.running_since && !over && !s.ended_at
  return {
    elapsed, remaining: Math.max(0, s.phase_length_s - elapsed), over, running,
    paused: !running && !over && !s.ended_at,
  }
}

/** The clock ran out while nobody was here.
 *
 *  Only a RUNNING session can be away — a paused one was left deliberately —
 *  and the test is how far the unclamped run overshoots the phase, not whether
 *  the phase is over: an interval that ended twenty seconds ago in a throttled
 *  tab is over, not abandoned. The surface never auto-continues from here,
 *  whatever the setting says: rolling on is a live screen's behaviour, not a
 *  thing time does in the dark. */
export function wasAway(s: FocusSession, nowMs: number): boolean {
  if (!s.running_since || s.ended_at) return false
  const room = Math.max(0, s.phase_length_s - s.phase_elapsed_s)
  return runS(s, nowMs) > room + AWAY_GRACE_S
}

// ── the queue ──────────────────────────────────────────────────────────────

const keyOf = (list: string | null, uid: string | null) => `${list ?? ''}\0${uid ?? ''}`

function taskIndex(tasks: Task[]): Map<string, Task> {
  const m = new Map<string, Task>()
  for (const t of tasks) m.set(keyOf(t.list, t.uid), t)
  return m
}

/** No list failed: the default, so a caller with nothing to report — and every
 *  pure-function test — passes nothing. */
const NO_FAILED_LISTS: ReadonlySet<string> = new Set()

/** Whether a row is finished, by the rule the server applies when it moves the
 *  cursor (`_resolved_day_rows`): a note or habit by its own stamp; a task by
 *  its VTODO — done OR cancelled, since neither is work left to do; and a task
 *  row whose task is gone once the tasks have loaded, because there is nothing
 *  left to work. Before they load a task row is open, which is the direction a
 *  loading gap may be wrong in — the surface must not sync off a blank.
 *
 *  A task from a list in `failedLists` is the same gap, list by list. The
 *  fan-out is `allSettled`, so one list answering 500 leaves its tasks OUT of
 *  the array while `loaded` flips true — and "gone once loaded" then counted
 *  every task on that list as done: the surface printed "All done." over open
 *  work, offered End, and sent a `sync` off a client-only misjudgement. A row
 *  whose list did not load is UNKNOWN, and unknown is open. */
function finished(
  e: DayEntry, byKey: Map<string, Task>, tasksLoaded: boolean,
  failedLists: ReadonlySet<string>,
): boolean {
  if (e.kind !== 'task') return !!e.done_at
  const task = byKey.get(keyOf(e.list, e.uid))
  if (!task) return tasksLoaded && !failedLists.has(e.list ?? '')
  return rowDone(e, task, true) || task.cancelled
}

export interface FocusQueue {
  /** The row the server names, if it is still open; else null. */
  current: DayEntry | null
  next: DayEntry | null
  /** Open rows behind `next`. */
  remaining: number
  /** Every open row in queue order, `current` first when there is one. */
  open: DayEntry[]
}

/** The open rows in the order the session works them: habit rows first, then
 *  the rest, each in plan order — the order Today paints — with done, dropped,
 *  rolled and set-aside rows gone.
 *
 *  PAINTS ONLY. `current` is whatever `s.entry_id` names; this never elects a
 *  row of its own, so nothing here can disagree with the server about what is
 *  being worked and drive a write off that disagreement. */
export function queueOf(
  entries: DayEntry[], tasks: Task[], tasksLoaded: boolean, s: FocusSession | null,
  /** Ids of the lists whose fetch failed — `TaskData.taskListsFailed`. */
  failedLists: ReadonlySet<string> = NO_FAILED_LISTS,
): FocusQueue {
  const byKey = taskIndex(tasks)
  const passed = new Set(s?.passed ?? [])
  const live = orderEntries(entries).filter((e) =>
    !e.dropped_at && !e.rolled_to && !passed.has(e.entry_id)
    && !finished(e, byKey, tasksLoaded, failedLists))
  const ordered = [
    ...live.filter((e) => e.kind === 'habit'),
    ...live.filter((e) => e.kind !== 'habit'),
  ]
  const current = (s?.entry_id && ordered.find((e) => e.entry_id === s.entry_id)) || null
  const rest = current ? ordered.filter((e) => e !== current) : ordered
  const open = current ? [current, ...rest] : rest
  return {
    current,
    next: current ? rest[0] ?? null : null,
    remaining: current ? Math.max(0, rest.length - 1) : rest.length,
    open,
  }
}

/** The one fact that may send the surface to `sync`: the row the server named
 *  is no longer open — ticked elsewhere, dropped, rolled, cancelled, gone.
 *  After a sync the server names a row that IS open, so this cannot re-fire;
 *  a disagreement about which row comes NEXT never reaches here. */
export function currentFinished(
  entries: DayEntry[], tasks: Task[], tasksLoaded: boolean, s: FocusSession | null,
  failedLists: ReadonlySet<string> = NO_FAILED_LISTS,
): boolean {
  if (!s?.entry_id) return false
  const e = entries.find((x) => x.entry_id === s.entry_id)
  if (!e) return true
  if (e.dropped_at || e.rolled_to) return true
  return finished(e, taskIndex(tasks), tasksLoaded, failedLists)
}

// ── the cap ────────────────────────────────────────────────────────────────

/** A row stops at its estimate when it has one and either says so or, having
 *  said nothing, the account's default says so. A row with no estimate has
 *  nothing to stop at. */
export function isCapped(e: DayEntry, capDefault: boolean): boolean {
  return e.estimate_minutes != null && (e.capped ?? capDefault)
}

/** Seconds this row has been worked, the live run included when it is the row
 *  being credited in a focus phase — what "12m worked" is painted from. */
export function workedNow(e: DayEntry, s: FocusSession | null, nowMs: number): number {
  const banked = e.worked_seconds ?? 0
  if (!s || s.phase !== 'focus' || s.entry_id !== e.entry_id) return banked
  return banked + (elapsedIn(s, nowMs) - s.phase_elapsed_s)
}

export function capReached(
  e: DayEntry, s: FocusSession | null, nowMs: number, capDefault: boolean,
): boolean {
  return isCapped(e, capDefault) && workedNow(e, s, nowMs) >= e.estimate_minutes! * 60
}

// ── the next phase, optimistically ─────────────────────────────────────────

/** What the server will answer to `next` — painted at once so the clock does
 *  not stall for a round trip, then replaced by the DTO. Mirrors
 *  `service._focus_next_phase`: a finished focus phase is counted, the long
 *  break comes every N of them (never, for 0), and "keep going" skips the
 *  break without un-counting the interval. */
export function nextPhase(
  s: FocusSession, settings: FocusSettings, skipBreak: boolean, nowMs: number,
): FocusSession {
  let phase: FocusPhase
  let intervals = s.intervals_done
  if (s.phase === 'focus') {
    intervals += 1
    phase = skipBreak ? 'focus'
      : settings.longEvery > 0 && intervals % settings.longEvery === 0 ? 'long_break'
        : 'break'
  } else {
    phase = 'focus'
  }
  return {
    ...s, phase, intervals_done: intervals,
    phase_length_s: phaseLengthS(phase, settings), phase_elapsed_s: 0,
    running_since: new Date(nowMs).toISOString(),
  }
}
