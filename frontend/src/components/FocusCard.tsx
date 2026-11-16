// Field notes' focus card on Today: the next thing to work on, with the
// highlighter swept behind it, and the one button that works the day.
//
// It is the focus session the full-screen Focus view keeps (api.focus), shown
// small: Start working begins it, Pause and Resume hold and continue it, in
// place. Which row is next is `queueOf` (focus.ts), the order the session works
// the plan in, so the card and the Focus view never disagree. The title opens
// the full Focus view, as Start working did before.
//
// Every label here is an existing one (today.startWorking, focus.pause,
// focus.resume). The card carries the session's own state on its button
// (`aria-pressed` while running) and reports whether it is running, which the
// day's drawing answers with its focus loop.
import { useEffect, useMemo, useState } from 'react'
import { api, type DayEntry, type FocusSession, type List, type Task } from '../api'
import { clockOf, queueOf } from '../focus'
import { useI18n } from '../i18n'
import { fmtClock } from '../time'
import { useTimeFormat } from '../timeformat'
import { entryTitle } from './TodayView'

export function FocusCard({ day, entries, tasks, tasksLoaded, lists, rev, onOpen, onRunning }: {
  day: string
  entries: DayEntry[]
  tasks: Task[]
  tasksLoaded: boolean
  lists: List[]
  /** Bumped by the shell on a change elsewhere; the session is read again. */
  rev?: number
  onOpen?: () => void
  onRunning: (running: boolean) => void
}) {
  const { t: tr, locale } = useI18n()
  const timeFormat = useTimeFormat()
  const [session, setSession] = useState<FocusSession | null>(null)
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    let live = true
    Promise.resolve().then(() => api.focus(day))
      .then((s) => { if (live) setSession(s ?? null) })
      .catch(() => { /* no session to show */ })
    return () => { live = false }
  }, [day, rev])

  const queue = useMemo(() => queueOf(entries, tasks, tasksLoaded, session), [entries, tasks, tasksLoaded, session])
  const clock = session && !session.ended_at ? clockOf(session, now) : null
  const running = !!clock?.running

  // No ticking clock: the card shows no countdown. It wakes once, when a
  // running phase runs out, so the button stops offering Pause.
  useEffect(() => {
    if (!clock?.running) return
    const t = setTimeout(() => setNow(Date.now()), clock.remaining * 1000 + 50)
    return () => clearTimeout(t)
  }, [clock?.running, clock?.remaining])
  useEffect(() => { onRunning(running) }, [running, onRunning])
  useEffect(() => () => onRunning(false), [onRunning])

  const next = queue.current ?? queue.open[0] ?? null
  if (!next) return null
  const task = next.kind === 'task' ? tasks.find((t) => t.list === next.list && t.uid === next.uid) : undefined
  const title = entryTitle(next, task, tasksLoaded, tr)
  const list = lists.find((l) => l.id === next.list)?.name
  const due = task?.due && !task.due_is_date ? fmtClock(task.due, timeFormat, locale) : null

  const act = async (call: () => Promise<FocusSession>) => {
    setBusy(true)
    try {
      setSession(await call())
      setNow(Date.now())
    } catch { /* the read on the next change corrects the card */ } finally {
      setBusy(false)
    }
  }
  const live = session && !session.ended_at
  const [label, press] = !live || clock?.over
    ? [tr('today.startWorking'), () => (live ? onOpen?.() : void act(() => api.startFocus(day)))]
    : running
      ? [tr('focus.pause'), () => void act(() => api.focusClock(day, { action: 'pause' }))]
      : [tr('focus.resume'), () => void act(() => api.focusClock(day, { action: 'resume' }))]

  return (
    <section className="focus-card" aria-label={title}>
      {due && <span className="focus-card__time">{due}</span>}
      <button type="button" className="focus-card__title" onClick={onOpen} disabled={!onOpen}>
        <span className="focus-card__mark" aria-hidden="true" />
        <span className="focus-card__text">{title}</span>
      </button>
      <div className="focus-card__foot">
        {list && <span className="focus-card__meta">{list}</span>}
        <button type="button" className={`btn focus-card__go ${running ? 'on' : ''}`}
          aria-pressed={running} disabled={busy} onClick={press}>
          {label}
        </button>
      </div>
    </section>
  )
}
