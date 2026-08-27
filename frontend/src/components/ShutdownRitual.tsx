// The evening ritual: what happened, what follows you, and a line about how it
// went.
//
// The counterpart to `PlanRitual`, and deliberately the same shape — three
// steps, skippable, closable, a stepped overlay rather than an inline mode. The
// inline Review the tab already has is untouched and stays the cheap glance;
// this is the one you walk at the end, and the difference between them is that
// this one ASKS you things.
//
// The middle step is the whole reason it exists. Unfinished work already
// survives — the automatic carry moves it forward once — but "survives" is not
// the same as "decided about", and a list nobody decided about is the one that
// stops being read. Here each row is a question with three honest answers:
// tomorrow, a day you name, or off the plan. Leaving it alone is the fourth,
// costs nothing, and is what the carry is still there for.
//
// Nothing here scores the day. There is no percentage, no streak and no colour
// on the numbers — the same call the habit count makes, for the same reason: a
// surface that grades you is a surface you stop opening.

import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { DayEntry, Task } from '../api'
import { useEscape } from '../hooks'
import { useTimeFormat } from '../timeformat'
import { fmtClock, fmtDuration } from '../time'
import { taskKey } from '../order'
import { textDir } from '../util'

const STEPS = ['How today went', 'What follows you', 'Anything to note?'] as const

/** How far ahead "a day you name" may reach.
 *
 *  A fortnight, matching the look-back's reach in the other direction. Long
 *  enough for "not this week, pick it up Monday" and short enough that this
 *  stays a shutdown rather than a planner for next month — which the Today tab
 *  deliberately is not. */
const ROLL_DAYS = 14

export function ShutdownRitual({
  day, entries, offPlan, planned, done, doneMinutes, unestimated, shutdownAt,
  reflection, renderRow, colorOf, isDone, titleOf, onRoll, onDrop, onReflect,
  onShutdown, onClose,
}: {
  day: string
  /** The day's live rows, in reading order. */
  entries: DayEntry[]
  /** Tasks finished today that were never on the plan. */
  offPlan: Task[]
  /** Minutes planned, and minutes of what got done. */
  planned: number
  doneMinutes: number
  /** How many rows are finished. */
  done: number
  /** How many rows carry no estimate — what the minutes are silent about. */
  unestimated: number
  shutdownAt: string | null
  reflection: string | null
  renderRow: (e: DayEntry) => ReactNode
  colorOf: (listId: string | null) => string | null
  /** Whether a row counts as finished. Lifted in rather than re-derived: a task
   *  row's doneness is its VTODO's, a note's and a habit's is the entry's own,
   *  and `TodayView.rowDone` is the one place that knows which. A second
   *  opinion here is how this list comes to disagree with the count above it. */
  isDone: (e: DayEntry) => boolean
  /** What a row reads as. Lifted in for the same reason `isDone` is: a task
   *  entry carries no title of its own — the VTODO's summary is the truth, and
   *  only the view that holds the tasks can resolve it. Deriving one here
   *  printed "(this task)" against every task row on the one screen whose whole
   *  job is deciding about them, which is how this came to be a prop. */
  titleOf: (e: DayEntry) => string
  onRoll: (e: DayEntry, to: string) => void
  onDrop: (e: DayEntry) => void
  onReflect: (text: string) => void
  onShutdown: () => void
  onClose: () => void
}) {
  const [step, setStep] = useState(0)
  const scrimPress = useRef(false)
  useEscape(onClose)

  const unfinished = entries.filter((e) => !isDone(e))
  const last = step === STEPS.length - 1

  // How many rows the owner DECIDED about in this ritual — rolled to another
  // day, or dropped. `unfinished` empties either way: a rolled row leaves the
  // day entirely, so "nothing is unfinished" is true after moving everything to
  // tomorrow exactly as it is after ticking everything off, and step two said
  // "Everything on today is done. Nothing to carry." to a day where nothing had
  // been done and everything was being carried. The two exits are
  // indistinguishable from the list alone; this is what tells them apart.
  //
  // Held HERE rather than in `FollowsStep`, which unmounts when the owner steps
  // forward: a counter inside it would reset on Back and tell the lie again.
  const [decided, setDecided] = useState(0)
  const decide = <T extends unknown[]>(fn: (...a: T) => void) => (...a: T) => {
    setDecided((n) => n + 1)
    fn(...a)
  }

  return (
    <div className="overlay"
      onMouseDown={(e) => { scrimPress.current = e.target === e.currentTarget }}
      onClick={(e) => {
        if (e.target === e.currentTarget && scrimPress.current) onClose()
        scrimPress.current = false
      }}>
      <div className="modal plan-ritual" role="dialog" aria-modal="true"
        aria-label="Shut down the day" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{STEPS[step]}</span>
          <span className="plan-step mono">{step + 1} of {STEPS.length}</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {step === 0 && (
          <DoneStep entries={entries} offPlan={offPlan} planned={planned}
            done={done} doneMinutes={doneMinutes} unestimated={unestimated}
            shutdownAt={shutdownAt} renderRow={renderRow} colorOf={colorOf} />
        )}
        {step === 1 && (
          <FollowsStep day={day} unfinished={unfinished} titleOf={titleOf} decided={decided}
            onRoll={decide(onRoll)} onDrop={decide(onDrop)} />
        )}
        {step === 2 && (
          <ReflectStep reflection={reflection} onReflect={onReflect} />
        )}

        <div className="modal-actions plan-actions">
          {step > 0 && (
            <button className="btn ghost" onClick={() => setStep(step - 1)}>Back</button>
          )}
          <span className="spacer" />
          {!last && (
            <button className="btn ghost" onClick={() => setStep(step + 1)}>Skip</button>
          )}
          {last ? (
            <button className="btn" onClick={onShutdown}>
              {shutdownAt ? 'Done' : 'Shut down'}
            </button>
          ) : (
            <button className="btn" onClick={() => setStep(step + 1)}>Next</button>
          )}
        </div>
      </div>
    </div>
  )
}

/** Step one: what happened. */
function DoneStep({ entries, offPlan, planned, done, doneMinutes, unestimated,
  shutdownAt, renderRow, colorOf }: {
  entries: DayEntry[]
  offPlan: Task[]
  planned: number
  done: number
  doneMinutes: number
  unestimated: number
  shutdownAt: string | null
  renderRow: (e: DayEntry) => ReactNode
  colorOf: (listId: string | null) => string | null
}) {
  const tf = useTimeFormat()
  return (
    <div className="plan-body plan-scroll">
      {shutdownAt && (
        // Said here rather than on the button that opens this, because this is
        // where somebody who came back would look. Coming back is allowed and
        // expected — an evening thought belongs in the same reflection as the
        // rest — so the state is reported and nothing is refused.
        <p className="plan-hint">
          You shut today down at {fmtClock(shutdownAt, tf)}. Anything you change
          from here still lands on today.
        </p>
      )}
      {/* FACTUAL, and nothing more. No percentage, no ratio coloured against a
          target, no streak. The habit count three files away makes the same
          call and says why: a surface that grades you is a surface you stop
          opening, and this is the one you would be opening at the end of a hard
          day. */}
      <p className="plan-hint">
        {done} of {entries.length} done
        {planned > 0 && ` · ${fmtDuration(doneMinutes)} of ${fmtDuration(planned)} planned`}
        {/* What the minutes are SILENT about, in the same words the day's own
            strip and the planning ritual use. Without it a day whose finished
            rows happened to be the unestimated ones reads "0m of 1h 20m
            planned" and looks like a day nothing happened on — which is the
            exact verdict this step is written to avoid. */}
        {planned > 0 && unestimated > 0 && ` · ${unestimated} not estimated`}
      </p>
      {entries.length > 0 && (
        <ul className="today-list">{entries.map(renderRow)}</ul>
      )}
      {offPlan.length > 0 && (
        <>
          {/* Usually the more interesting half, and the half a plan cannot
              know: work that happened without ever being planned. */}
          <div className="label section-label">Done off-plan</div>
          <ul className="today-list" aria-label="Done off-plan">
            {offPlan.map((t) => (
              <li key={taskKey(t)} className="today-row">
                <span className="today-check-gap today-mark mono" role="img"
                  aria-label="Done">✓</span>
                <span className="today-kind-mark" data-kind="task" role="img"
                  aria-label="Task">
                  <span className="today-kind-box" style={colorOf(t.list)
                    ? { background: colorOf(t.list)! } : undefined} />
                </span>
                <span className="today-title" dir={textDir(t.summary)}>
                  {t.summary || '(untitled)'}
                </span>
                <span className="today-due mono">{fmtClock(t.completed_at!, tf)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {entries.length === 0 && offPlan.length === 0 && (
        <p className="empty">Nothing on today, and nothing finished off-plan.</p>
      )}
    </div>
  )
}

/** Step two: what follows you into tomorrow. */
function FollowsStep({ day, unfinished, titleOf, decided, onRoll, onDrop }: {
  day: string
  unfinished: DayEntry[]
  titleOf: (e: DayEntry) => string
  /** Rows moved or dropped in this ritual — see the parent. Nonzero means the
   *  list emptied because the owner DECIDED about it, not because it was done. */
  decided: number
  onRoll: (e: DayEntry, to: string) => void
  onDrop: (e: DayEntry) => void
}) {
  const tomorrow = addDayKey(day, 1)
  // The floor for the date field, so the browser's own picker cannot offer a day
  // the server would refuse. The rule is enforced server-side regardless
  // (`roll_entry` will not move work backwards); this only stops the control
  // inviting it.
  const max = addDayKey(day, ROLL_DAYS)

  // Everything a "move it all" could actually move. A habit occurrence is not
  // in it — see the row below — so on a day whose only leftovers are habits the
  // button is correctly absent rather than present and inert.
  const movable = unfinished.filter((e) => e.kind !== 'habit')

  if (!unfinished.length) {
    return (
      <div className="plan-body">
        {/* Two exits, two sentences. "Done" is the one thing this step exists to
            be able to say, and it has to stay true: an owner who moved every row
            to tomorrow decided about their day, they did not finish it. */}
        <p className="empty">
          {decided > 0
            ? 'Everything on today is decided. Nothing left to carry.'
            : 'Everything on today is done. Nothing to carry.'}
        </p>
      </div>
    )
  }
  return (
    <div className="plan-body plan-scroll">
      <p className="plan-hint">
        Leave anything alone and it carries by itself — this is for the ones you
        want to decide about. Deciding makes a row leave this list.
      </p>
      {/* The whole-list version of the arm every row has, and worth its own
          control: "none of this happened today, all of it happens tomorrow" is
          the commonest true answer, and paying for it one row at a time is what
          makes a shutdown feel like paperwork. Offered from two rows up, because
          on one leftover the per-row button already says it. */}
      {movable.length > 1 && (
        <div className="shut-all">
          <button type="button" className="btn ghost"
            onClick={() => { for (const e of movable) onRoll(e, tomorrow) }}>
            Move all {movable.length} to tomorrow
          </button>
        </div>
      )}
      <ul className="today-list">
        {unfinished.map((e) => {
          // `titleOf` is empty only in the instant before the tasks land, and a
          // blank row on the one screen whose job is deciding about rows is
          // worse than a placeholder. It is never what a loaded day shows.
          const name = titleOf(e) || '(this task)'
          return (
            <li key={e.entry_id} className="today-row shut-row">
              <span className="today-title" dir={textDir(name)}>{name}</span>
              {/* The arms on their OWN line, always, rather than fitted beside
                  the title when they happen to fit. Measured in a browser: at
                  the dialog's width the last of the three wrapped anyway, and
                  wrapped to a different indent on every row — so a list whose
                  whole job is being scanned had a ragged left edge and no two
                  rows the same height. One shape, every row, every width. */}
              <span className="shut-arms">
                {/* A habit occurrence has no move arm, and cannot: tomorrow gets
                    its own from the rule, so moving one would either duplicate
                    it or fabricate an occurrence on a day the rule does not
                    schedule. Declining it is still a real answer — "I did not do
                    this today". */}
                {e.kind !== 'habit' && (
                  <>
                    <button type="button" className="btn ghost shut-act"
                      aria-label={`Move ${name} to tomorrow`}
                      onClick={() => onRoll(e, tomorrow)}>Tomorrow</button>
                    <input type="date" className="input shut-date"
                      aria-label={`Move ${name} to a day`}
                      min={tomorrow} max={max} value=""
                      onChange={(ev) => { if (ev.target.value) onRoll(e, ev.target.value) }} />
                  </>
                )}
                <button type="button" className="btn ghost shut-act"
                  aria-label={`Take ${name} off the plan`}
                  onClick={() => onDrop(e)}>Off the plan</button>
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/** Step three: a line about the day. */
function ReflectStep({ reflection, onReflect }: {
  reflection: string | null
  onReflect: (text: string) => void
}) {
  const [draft, setDraft] = useState(reflection ?? '')

  // Committed on UNMOUNT as well as on blur, and the effect ADDS a path rather
  // than replacing one. Browsers fire no `blur`/`focusout` for a focused element
  // removed from the DOM (Chrome and Safari, so every iOS install), and Escape —
  // `useEscape(onClose)` on the window — unmounts this whole overlay. So the one
  // field in the app that holds free prose, under a hint promising "Kept with
  // the day", threw it away for the one closer that does not blur first. The ✕
  // and the scrim were always safe: their mousedown blurs the field.
  //
  // Read through refs so the cleanup can run once, on unmount, and still see the
  // LAST draft — a cleanup depending on `draft` would fire on every keystroke,
  // which is the write storm the blur handler exists to avoid.
  const latest = useRef(draft)
  latest.current = draft
  const saved = useRef(reflection ?? '')
  saved.current = reflection ?? ''
  const commit = useRef(onReflect)
  commit.current = onReflect
  useEffect(() => () => {
    if (latest.current !== saved.current) commit.current(latest.current)
  }, [])

  return (
    <div className="plan-body">
      <label className="plan-label" htmlFor="shut-reflect">
        How did today go?
      </label>
      <textarea id="shut-reflect" className="input shut-reflect" rows={4} autoFocus
        value={draft} placeholder="A sentence is plenty."
        aria-label="A note about today"
        onChange={(e) => setDraft(e.target.value)}
        // On blur rather than per keystroke: this is prose, and a PATCH per
        // character would be a write storm for a field nobody is racing on.
        // `saved` is updated by the render that follows, so the unmount effect
        // above does not send it a second time.
        onBlur={() => { if (draft !== (reflection ?? '')) onReflect(draft) }} />
      <p className="plan-hint">
        Kept with the day. You will see it whenever you look back at today.
      </p>
    </div>
  )
}

/** `day` plus `n` days, as a day key. Local-midnight parsing, like every other
 *  day-key arithmetic in this app: a bare "2026-08-24" parses as UTC and lands
 *  on the previous day for every viewer west of it. */
function addDayKey(day: string, n: number): string {
  const d = new Date(`${day}T00:00`)
  d.setDate(d.getDate() + n)
  const p = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
