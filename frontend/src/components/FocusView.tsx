// The focus surface: today's queue, worked against a clock.
//
// The display's rolling face (`DisplayView.NowFace`) brought inside the app and
// given hands: the one thing you are on, in the largest type the screen holds,
// the one after it in small, a count of what is behind that — and a pomodoro
// clock the row rides. A row is either CAPPED at its estimate, in which case
// the surface passes it on the moment its worked time reaches that figure, or
// runs UNTIL DONE, in which case it stays until it is ticked or set aside.
//
// Three things this file is built around, and the header comments below each
// carry the argument:
//
//  * EVERY NUMBER IS DERIVED, NEVER COUNTED. The server keeps anchors — when the
//    phase's current run began, how much was banked before it — and the seconds
//    on screen are computed from those and the wall clock on every tick
//    (`focus.ts`). Two windows therefore agree, a refresh loses nothing, and
//    the credit a row receives can never exceed the phase it was earned in.
//  * THE SERVER NAMES THE ROW. `session.entry_id` is what is being worked; the
//    queue this paints is ordered like Today but never elects a row of its own.
//    The one fact that sends the surface back to the server is "the row it
//    named is finished" — ticked here, on a phone, or in Thunderbird.
//  * A CLOCK THAT RAN OUT WHILE NOBODY WAS HERE WAITS. Rolling straight into
//    the next phase is a setting, and it means a live screen rolling on; it
//    does not mean time passing in the dark. `wasAway` draws the line.
//
// It reads the day with `api.day` — a pure read — and never `openDay`. Today is
// the only opener (see HomeView's day-plan module for the same rule and the
// same reason): a session that planned a day as a side effect of a page load
// would put a plan in the record nobody made. Unplanned, it says so and points
// at Today.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type DayPlan, type FocusSession, type Task } from '../api'
import { readCachedDayPlan } from '../cache'
import { playChime, unlockChime } from '../chime'
import { useTaskData } from '../data'
import {
  capReached, clockOf, currentFinished, elapsedIn, isCapped, nextPhase, queueOf, wasAway,
  workedNow, type FocusSettings,
} from '../focus'
import { useEscape, useToday } from '../hooks'
import { useI18n } from '../i18n'
import { notifyPermission, requestNotify, showNotify } from '../notify'
import { fmtClock, fmtCountdown, fmtDuration } from '../time'
import { useTimeFormat } from '../timeformat'
import { makeGuard, textDir } from '../util'
import { entryTitle } from './TodayView'

export function FocusView({ rev, focusRev, onExpire, onLeave, settings }: {
  /** Bumped by App on every data change the server publishes; re-reads the day. */
  rev: number
  /** Bumped on `focus_updated` alone; re-reads the session. Kept apart from
   *  `rev` because a clock transition every few minutes must not refetch every
   *  list and task in every open tab. */
  focusRev: number
  onExpire: () => void
  onLeave: () => void
  settings: FocusSettings
}) {
  const { locale, t: tr } = useI18n()
  const tf = useTimeFormat()
  const expire = useRef(onExpire)
  expire.current = onExpire
  const guard = useMemo(() => makeGuard(() => expire.current()), [])
  const { tasks, loaded, toggle } = useTaskData()
  const today = useToday()
  useEscape(onLeave)

  // ── the day and the session ────────────────────────────────────────────
  const [plan, setPlan] = useState<DayPlan | null>(() => readCachedDayPlan(today))
  const [planTried, setPlanTried] = useState(false)
  // `undefined` until the first read lands: "no session" and "not asked yet"
  // are different states, and only one of them offers a Start button.
  const [session, setSession] = useState<FocusSession | null | undefined>(undefined)
  const planToken = useRef(0)
  const sessionToken = useRef(0)

  useEffect(() => {
    const mine = ++planToken.current
    void guard(async () => {
      const p = await api.day(today)
      if (mine !== planToken.current) return
      setPlan(p ?? null)
      setPlanTried(true)
    })
  }, [today, rev, guard])

  useEffect(() => {
    const mine = ++sessionToken.current
    void guard(async () => {
      const s = await api.focus(today)
      if (mine !== sessionToken.current) return
      setSession(s ?? null)
    })
  }, [today, focusRev, guard])

  // The tick. One a second, whatever the state: the cost is a re-render of a
  // surface with two rows on it.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  // ── derived ────────────────────────────────────────────────────────────
  const entries = useMemo(
    () => (plan && plan.day === today ? plan.entries : []), [plan, today])
  const queue = useMemo(
    () => queueOf(entries, tasks, loaded, session ?? null), [entries, tasks, loaded, session])
  // The tally counts EVERY open row, set-aside ones included: "3 / 8 done" is a
  // fact about the day, and setting a row aside did not do it.
  const openAll = useMemo(() => queueOf(entries, tasks, loaded, null).open.length,
    [entries, tasks, loaded])
  const liveTotal = useMemo(
    () => entries.filter((e) => !e.dropped_at && !e.rolled_to).length, [entries])
  const current = queue.current
  const currentTask: Task | undefined = current?.kind === 'task'
    ? tasks.find((t) => t.list === current.list && t.uid === current.uid) : undefined
  const live = !!session && !session.ended_at
  const clock = session ? clockOf(session, now) : null
  const away = !!session && live && wasAway(session, now)
  const onBreak = !!session && session.phase !== 'focus'

  // ── writes ─────────────────────────────────────────────────────────────
  // Every one invalidates the session read in flight, so a stale answer cannot
  // paint over what the server just said. `guard` swallows a failure into a
  // toast and answers undefined, in which case the optimistic paint stands
  // until the next read corrects it — the same bargain TodayView makes.
  const send = useCallback(async (call: () => Promise<FocusSession>) => {
    sessionToken.current += 1
    const dto = await guard(call)
    if (dto) setSession(dto)
    return dto
  }, [guard])

  const start = useCallback(() => {
    // Inside the gesture, because that is the only place the browser lets a
    // page unlock audio or ask to notify.
    unlockChime()
    if (settings.notify && notifyPermission() === 'default') void requestNotify()
    void send(() => api.startFocus(today))
  }, [send, settings.notify, today])

  const pause = useCallback(() => {
    setSession((s) => (s && s.running_since
      ? { ...s, phase_elapsed_s: elapsedIn(s, Date.now()), running_since: null } : s))
    void send(() => api.focusClock(today, { action: 'pause' }))
  }, [send, today])

  const resume = useCallback(() => {
    unlockChime()
    setSession((s) => (s && !s.running_since
      ? { ...s, running_since: new Date().toISOString() } : s))
    void send(() => api.focusClock(today, { action: 'resume' }))
  }, [send, today])

  const next = useCallback((skipBreak = false) => {
    const s = session
    if (!s) return
    unlockChime()
    setSession(nextPhase(s, settings, skipBreak, Date.now()))
    void send(() => api.focusClock(today, {
      action: 'next', expect_phase: s.phase, expect_intervals: s.intervals_done,
      skip_break: skipBreak,
    }))
  }, [send, session, settings, today])

  const sync = useCallback(() => {
    void send(() => api.focusClock(today, { action: 'sync' }))
  }, [send, today])

  const end = useCallback(() => {
    void send(() => api.focusClock(today, { action: 'end' }))
  }, [send, today])

  const pass = useCallback((entryId: string) => {
    // Paint the move at once: the row is set aside and the next one steps up.
    setSession((s) => (s && s.entry_id === entryId
      ? { ...s, passed: [...s.passed, entryId], entry_id: queue.next?.entry_id ?? null } : s))
    void send(() => api.focusCursor(today, { action: 'pass', entry_id: entryId }))
  }, [queue.next, send, today])

  const again = useCallback(() => {
    void send(() => api.focusCursor(today, { action: 'again' }))
  }, [send, today])

  const select = useCallback((entryId: string) => {
    void send(() => api.focusCursor(today, { action: 'select', entry_id: entryId }))
  }, [send, today])

  /** Tick the row being worked. A task through the same call Today's checkbox
   *  uses — its doneness is its VTODO, and `patch_day_entry` refuses `done`
   *  on one — a note or habit through the day. Neither calls `sync` itself:
   *  the paint below makes the row finished, and the effect that watches for
   *  exactly that does the rest. */
  const tickCurrent = useCallback(async () => {
    if (!current) return
    if (current.kind === 'task') {
      if (currentTask && !currentTask.completed) await toggle(currentTask)
      return
    }
    const id = current.entry_id
    setPlan((p) => (p && p.day === today
      ? { ...p, entries: p.entries.map((e) => (e.entry_id === id
        ? { ...e, done_at: new Date().toISOString() } : e)) }
      : p))
    await guard(() => api.patchDayEntry(today, id, { done: true }))
  }, [current, currentTask, guard, today, toggle])

  const setCap = useCallback(async (entryId: string, capped: boolean) => {
    setPlan((p) => (p && p.day === today
      ? { ...p, entries: p.entries.map((e) => (e.entry_id === entryId ? { ...e, capped } : e)) }
      : p))
    const dto = await guard(() => api.patchDayEntry(today, entryId, { capped }))
    setPlan((p) => (p && p.day === today
      ? { ...p, entries: p.entries.map((e) => (e.entry_id === entryId
        ? { ...e, capped: dto ? dto.capped : e.capped } : e)) }
      : p))
  }, [guard, today])

  // ── the effects that make it roll ──────────────────────────────────────
  //
  // Each is guarded by a ref keyed on the state it reacts to, so a re-render
  // (there is one a second) and a second window cannot fire it twice. The
  // server is idempotent about all of them besides; these keep the wire quiet.

  // The row the server named has been finished — here, or anywhere else. Keyed
  // on the row AND `rev`: once asked, ask again only when the server has
  // published something new, so a client running ahead of its own write (a
  // tick whose PATCH is still in flight) asks once per round trip rather than
  // once per tick, and stops the moment the cursor moves.
  const synced = useRef<string | null>(null)
  useEffect(() => {
    if (!session || !live || !planTried) return
    if (!currentFinished(entries, tasks, loaded, session)) { synced.current = null; return }
    const key = `${session.entry_id}:${rev}`
    if (synced.current === key) return
    synced.current = key
    sync()
  }, [entries, tasks, loaded, session, live, planTried, rev, sync])

  // A capped row has used its estimate: set it aside and move on, mid-interval.
  const capped = useRef<string | null>(null)
  useEffect(() => {
    if (!session || !live || !current || session.phase !== 'focus') return
    if (!capReached(current, session, now, settings.capDefault)) return
    if (capped.current === current.entry_id) return
    capped.current = current.entry_id
    pass(current.entry_id)
  }, [current, live, now, pass, session, settings.capDefault])

  // The phase ran out. Once per phase: say so (chime, notification), and roll
  // on if the setting says to — but only for a LIVE screen. A phase that ended
  // while the owner was away is announced by the screen they come back to,
  // not by a sound in an empty room, and it never rolls on without them.
  const ended = useRef<string | null>(null)
  useEffect(() => {
    if (!session || !live || !clock || !clock.over) return
    const key = `${session.phase}:${session.intervals_done}`
    if (ended.current === key) return
    ended.current = key
    if (away) return
    const focusEnded = session.phase === 'focus'
    if (settings.chime) playChime(focusEnded ? 'focus' : 'break')
    if (settings.notify) {
      showNotify(
        tr(focusEnded ? 'focus.notify.focusOver' : 'focus.notify.breakOver'),
        current ? entryTitle(current, currentTask, loaded, tr) : '')
    }
    if (settings.autoContinue) next(false)
  }, [away, clock, current, currentTask, live, loaded, next, session, settings, tr])

  // The tab's title carries the clock, so a tab behind another still says
  // where the interval stands — the same lever DisplayView pulls for a panel's
  // name. Restored on the way out.
  useEffect(() => {
    if (!session || !live || !clock) { document.title = 'Smylte'; return }
    const name = current ? entryTitle(current, currentTask, loaded, tr) : tr('focus.title')
    document.title = `${fmtCountdown(clock.remaining)} · ${name} · Smylte`
  }, [clock, current, currentTask, live, loaded, session, tr])
  useEffect(() => () => { document.title = 'Smylte' }, [])

  // ── render ─────────────────────────────────────────────────────────────
  const state = !session ? 'idle' : session.ended_at ? 'ended'
    : away ? 'away' : clock?.over ? 'over' : clock?.running ? 'running' : 'paused'
  const phaseLabel = !session ? '' : state === 'away' ? tr('focus.phase.away')
    : state === 'paused' ? tr('focus.phase.paused')
      : state === 'over' ? tr(onBreak ? 'focus.phase.breakOver' : 'focus.phase.over')
        : tr(session.phase === 'focus' ? 'focus.phase.focus'
          : session.phase === 'break' ? 'focus.phase.break' : 'focus.phase.longBreak')

  const title = (e: typeof current) => (e ? entryTitle(e, e === current ? currentTask
    : tasks.find((t) => t.list === e.list && t.uid === e.uid), loaded, tr) : '')

  let body: React.ReactNode
  if (!planTried && !plan) {
    body = null
  } else if (!plan || !plan.planned) {
    body = (
      <>
        <p className="focus-empty">{tr('focus.notPlanned')}</p>
        {/* The way back is the header's button; a second one here would be
            two controls with one name on a screen that has nothing else. */}
        <p className="focus-hint">{tr('focus.notPlannedHint')}</p>
      </>
    )
  } else if (session === undefined) {
    body = null
  } else if (session === null || session.ended_at) {
    body = (
      <>
        {session?.ended_at
          ? <p className="focus-empty">{tr('focus.ended', { time: fmtClock(session.ended_at, tf, locale) })}</p>
          : <p className="focus-empty">{tr('focus.readyHeadline', { count: openAll })}</p>}
        <div className="focus-actions">
          <button type="button" className="btn" onClick={start}>
            {tr(session ? 'focus.startAgain' : 'focus.start')}
          </button>
        </div>
      </>
    )
  } else if (!current) {
    body = (
      <>
        <p className="focus-empty">
          {session.passed.length ? tr('focus.queueEmpty') : tr('focus.allDone')}
        </p>
        {session.passed.length > 0 && (
          <p className="focus-hint">{tr('focus.setAside', { count: session.passed.length })}</p>
        )}
        <div className="focus-actions">
          {session.passed.length > 0 && (
            <button type="button" className="btn" onClick={again}>{tr('focus.again')}</button>
          )}
          <button type="button" className="btn ghost" onClick={end}>{tr('focus.end')}</button>
        </div>
      </>
    )
  } else {
    const cap = isCapped(current, settings.capDefault)
    const worked = workedNow(current, session, now)
    body = (
      <>
        <div className="focus-phase" role="status">{phaseLabel}</div>
        <div className="focus-clock" aria-live="off">{fmtCountdown(clock!.remaining)}</div>
        {state === 'away' && <p className="focus-hint">{tr('focus.awayHint')}</p>}

        <div className="focus-now">
          <div className="focus-now__eyebrow">{tr(onBreak ? 'focus.upNext' : 'focus.now')}</div>
          <h1 className="focus-now__title" dir={textDir(title(current))}>{title(current)}</h1>
          <div className="focus-now__meta">
            {current.estimate_minutes != null && (
              <span>{tr('focus.est', { amount: fmtDuration(current.estimate_minutes) })}</span>
            )}
            {worked > 0 && (
              <span>{tr('focus.worked', { amount: fmtDuration(Math.round(worked / 60)) })}</span>
            )}
            {current.estimate_minutes != null && (
              <button type="button" className="focus-cap"
                aria-label={tr('focus.cap.aria')}
                onClick={() => void setCap(current.entry_id, !cap)}>
                {tr(cap ? 'focus.cap.capped' : 'focus.cap.open')}
              </button>
            )}
          </div>
          <div className="focus-actions">
            {!onBreak && (
              <button type="button" className="btn" onClick={() => void tickCurrent()}>
                {tr('focus.done')}
              </button>
            )}
            {!onBreak && (
              <button type="button" className="btn ghost" onClick={() => pass(current.entry_id)}>
                {tr('focus.notNow')}
              </button>
            )}
            {state === 'running' && (
              <button type="button" className="btn ghost" onClick={pause}>{tr('focus.pause')}</button>
            )}
            {state === 'paused' && (
              <button type="button" className="btn ghost" onClick={resume}>{tr('focus.resume')}</button>
            )}
            {(state === 'over' || state === 'away') && !onBreak && (
              <>
                <button type="button" className="btn ghost" onClick={() => next(false)}>
                  {tr('focus.takeBreak')}
                </button>
                <button type="button" className="btn ghost" onClick={() => next(true)}>
                  {tr('focus.keepGoing')}
                </button>
              </>
            )}
            {(state === 'over' || state === 'away') && onBreak && (
              <button type="button" className="btn ghost" onClick={() => next(false)}>
                {tr('focus.nextInterval')}
              </button>
            )}
            {state === 'running' && onBreak && (
              <button type="button" className="btn ghost" onClick={() => next(false)}>
                {tr('focus.skipBreak')}
              </button>
            )}
          </div>
        </div>

        {queue.next && (
          <div className="focus-next">
            <div className="focus-now__eyebrow">{tr('focus.next')}</div>
            <div className="focus-next__text" dir={textDir(title(queue.next))}>
              <button type="button" className="focus-pick" title={tr('focus.pickRow')}
                onClick={() => select(queue.next!.entry_id)}>
                {title(queue.next)}
              </button>
            </div>
            {queue.remaining > 0 && (
              <div className="focus-next__more">{tr('focus.behind', { count: queue.remaining })}</div>
            )}
          </div>
        )}
      </>
    )
  }

  return (
    <div className="focus" data-state={state} data-phase={session?.phase ?? ''}>
      <header className="focus-head">
        <span className="label">{tr('focus.title')}</span>
        {live && session && (
          <span className="focus-head__interval">
            {tr('focus.interval', { n: session.intervals_done + 1 })}
          </span>
        )}
        <span className="spacer" />
        {plan?.planned && (
          <span className="focus-head__tally">
            {tr('focus.tally', { done: liveTotal - openAll, total: liveTotal })}
          </span>
        )}
        <button type="button" className="btn ghost focus-back" onClick={onLeave}>
          {tr('focus.back')}
        </button>
      </header>
      <main className="focus-main">{body}</main>
      {live && current && (
        <footer className="focus-foot">
          <span className="spacer" />
          <button type="button" className="btn ghost" onClick={end}>{tr('focus.end')}</button>
        </footer>
      )}
    </div>
  )
}
