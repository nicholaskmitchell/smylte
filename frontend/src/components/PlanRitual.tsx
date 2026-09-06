// The morning ritual: three steps between an empty day and a day you have
// committed to.
//
// A stepped flow rather than the running total alone, because the total answers
// "am I overcommitted" and the ritual answers "what am I doing today" — and the
// second question is the one that goes unasked. Sunsama's is the model: it opens
// by asking when you want to stop, then walks picking, estimating and ordering,
// and warns when eight hours of work meets a six-hour window.
//
// THREE STEPS, NOT SIX, and both reductions were found by building it.
//
// The plan named a separate "leftovers" step. That would have been a THIRD
// surface for the same rows: the automatic carry already brings the last planned
// day's chosen work onto today, and everything older is already the "Still open
// from a recent plan" suggestion group. So that group is promoted to the top of
// the picking step and reworded there — it gets its moment without a screen of
// its own.
//
// Estimating and ordering were also separate, and are one screen here, because
// they are two passes over the same list: a screen for each would be ceremony
// rather than guidance. Committing is the last screen's button rather than a
// step, for the same reason — a screen whose only content is a button is a
// speed bump with a heading.
//
// It is CLOSABLE AT EVERY STEP and every step is skippable. A ritual you cannot
// leave is a wizard, and this one stands between the owner and a list they may
// simply have wanted to glance at.

import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { DayEntry, Task } from '../api'
import { useEscape } from '../hooks'
import { taskKey } from '../order'
import { textDir } from '../util'
import { fmtDuration } from '../time'
import { capacityInput, parseCapacity } from '../capacity'
import { useT, useTx } from '../i18n'

/** A suggestion group as `TodayView` builds it. */
export interface SuggestGroup {
  key: string
  label: string
  items: Task[]
}

/** The group that is really "what you did not finish last time". Promoted to
 *  the top of the picking step and reworded there — the label `TodayView` gives
 *  it is written for a quiet list under the day, not for the one screen whose
 *  whole job is to make you look at it. */
const LEFTOVER_KEY = 'open'

// Catalogue KEYS, not text — the same reason `TAB_LABELS` holds keys. The
// order is the ritual's order and the count is read off it, so this stays an
// array rather than three lookups.
const STEPS = ['plan.step.capacity', 'plan.step.pick', 'plan.step.shape'] as const

export function PlanRitual({
  entries, suggestions, capacity, planned, meetingMinutes, unestimated,
  committedAt, renderRow, colorOf, onCapacity, onAddTask, onCommit, onClose,
}: {
  /** The day's live rows, in reading order. */
  entries: DayEntry[]
  suggestions: SuggestGroup[]
  /** What the day's total is read against, or null when nobody has said. */
  capacity: number | null
  planned: number
  meetingMinutes: number
  /** How many rows carry no estimate — what the total is silent about. */
  unestimated: number
  committedAt: string | null
  /** The row renderer `TodayView` already owns, with its checkbox, its estimate
   *  cell and its drag handlers. Lifted in rather than rebuilt, so a row behaves
   *  identically inside the ritual and outside it. */
  renderRow: (e: DayEntry) => ReactNode
  colorOf: (listId: string | null) => string | null
  onCapacity: (minutes: number | null) => void
  onAddTask: (t: Task) => void
  onCommit: () => void
  onClose: () => void
}) {
  const tr = useT()
  const [step, setStep] = useState(0)
  /** Whether the press that started this click landed on the scrim itself. */
  const scrimPress = useRef(false)
  useEscape(onClose)

  const over = capacity != null && planned > capacity
  const last = step === STEPS.length - 1

  return (
    <div className="overlay"
      // The scrim's two-event dance, copied from `TaskModal` rather than
      // reinvented: a bare onClick fires whenever the release lands on the
      // scrim, so a text drag-select that began inside and finished outside
      // would discard the whole flow.
      onMouseDown={(e) => { scrimPress.current = e.target === e.currentTarget }}
      onClick={(e) => {
        if (e.target === e.currentTarget && scrimPress.current) onClose()
        scrimPress.current = false
      }}>
      <div className="modal plan-ritual" role="dialog" aria-modal="true"
        aria-label={tr('plan.aria')} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{tr(STEPS[step])}</span>
          <span className="plan-step mono">
            {tr('plan.stepOf', { n: step + 1, total: STEPS.length })}
          </span>
          <button className="icon-btn" onClick={onClose}
            aria-label={tr('common.close')}>✕</button>
        </div>

        {step === 0 && (
          <CapacityStep capacity={capacity} meetingMinutes={meetingMinutes}
            onCapacity={onCapacity} />
        )}
        {step === 1 && (
          <PickStep suggestions={suggestions} colorOf={colorOf} onAddTask={onAddTask} />
        )}
        {step === 2 && (
          <ShapeStep entries={entries} renderRow={renderRow} />
        )}

        {/* The running total rides along from the second step on, so the
            consequence of adding something is visible in the same breath as the
            adding — which is the whole reason the ritual is worth walking. */}
        {step > 0 && capacity != null && (
          <p className={`plan-total mono ${over ? 'over' : ''}`} role="status">
            {tr('plan.total', {
              planned: fmtDuration(planned), capacity: fmtDuration(capacity),
            })}
            {unestimated > 0 && tr('plan.unestimated', { count: unestimated })}
            {over && tr('plan.over', { amount: fmtDuration(planned - capacity) })}
          </p>
        )}

        <div className="modal-actions plan-actions">
          {step > 0 && (
            <button className="btn ghost" onClick={() => setStep(step - 1)}>{tr('common.back')}</button>
          )}
          <span className="spacer" />
          {!last && (
            // "Skip" and not a disabled Next: every step is optional, and a
            // flow that refused to advance would be the wizard this is not.
            <button className="btn ghost" onClick={() => setStep(step + 1)}>{tr('plan.skip')}</button>
          )}
          {last && over ? (
            // TWO NAMED ANSWERS RATHER THAN ONE UNNAMED ONE, and this is still
            // not a block: committing is one press either way. What changes is
            // that the press SAYS WHAT IT IS. "Start" on a day 80 minutes over
            // is a button that does not describe its own outcome, and the
            // warning underneath it was the only thing that did — read after
            // the decision rather than as part of it.
            //
            // Trimming goes back to the step where things are picked, because
            // that is where the day gets shorter; a button that only dismissed
            // the warning would be an acknowledgement, which is a toll rather
            // than a choice.
            <>
              <button className="btn ghost" onClick={() => setStep(1)}>
                {tr('plan.trim')}
              </button>
              <button className="btn" onClick={onCommit}>{tr('plan.commitAnyway')}</button>
            </>
          ) : last ? (
            <button className="btn" onClick={onCommit}>
              {committedAt ? tr('plan.done') : tr('plan.start')}
            </button>
          ) : (
            <button className="btn" onClick={() => setStep(step + 1)}>{tr('plan.next')}</button>
          )}
        </div>

        {/* Said at the moment of committing, in words, and it still never
            blocks — the buttons beside it do exactly what they say, and one of
            them commits. What this no longer is is the ONLY thing naming the
            over-commitment: the primary button names it too, so the decision is
            made with its consequence attached rather than beside it. A warning
            that stopped you would be a tool arguing with a decision it does not
            have the standing to make; one the button contradicts is worse. */}
        {last && over && (
          <p className="plan-warn" role="status">
            {tr('plan.warn', { amount: fmtDuration(planned - capacity!) })}
          </p>
        )}
      </div>
    </div>
  )
}

/** Step one: how long today is. */
function CapacityStep({ capacity, meetingMinutes, onCapacity }: {
  capacity: number | null
  meetingMinutes: number
  onCapacity: (minutes: number | null) => void
}) {
  const tr = useT()
  const tx = useTx()
  const [draft, setDraft] = useState(() => capacityInput(capacity))
  const [refused, setRefused] = useState(false)

  const commit = () => {
    const raw = draft.trim()
    if (!raw) { setRefused(false); if (capacity != null) onCapacity(null); return }
    // The clock is passed in here and matters: this is the field that takes
    // "until 6pm", and what it means depends on when it is typed. Resolved once,
    // now, into a plain number of minutes — see `capacity.ts`.
    const next = parseCapacity(raw, new Date())
    if (next == null) { setRefused(true); return }
    setRefused(false)
    setDraft(capacityInput(next))
    if (next !== capacity) onCapacity(next)
  }

  // Committed on UNMOUNT as well as on blur — the same gap `ReflectStep` has,
  // for the same reason: Escape unmounts the overlay and browsers fire no blur
  // for a focused element removed from the DOM, so "until 6pm" typed and then
  // Escaped was never stored. The effect ADDS a path; blur still commits, which
  // is what makes the parse error visible while the ritual is still open.
  //
  // It runs `commit` itself rather than sending the raw draft, so an unmount
  // resolves "until 6pm" against the clock exactly as a blur would — the whole
  // point of that function being where the parsing lives. A draft the parser
  // REFUSES writes nothing on unmount, which is the same answer blur gives; the
  // alternative would be storing a number nobody asked for from text the app has
  // already said it cannot read.
  const latest = useRef(commit)
  latest.current = commit
  useEffect(() => () => { latest.current() }, [])

  return (
    <div className="plan-body">
      <label className="plan-label" htmlFor="plan-capacity">
        {tr('plan.stopping')}
      </label>
      <input id="plan-capacity" className="input" autoFocus value={draft}
        placeholder={tr('plan.capacityPlaceholder')}
        aria-label={tr('plan.capacityAria')}
        onChange={(e) => { setDraft(e.target.value); setRefused(false) }}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit() } }} />
      {refused ? (
        // The parser refuses rather than guesses, so this is where that shows.
        // It names what it takes instead of saying "invalid", because the useful
        // half of a rejection is the example.
        <p className="plan-hint warn" role="status">
          {tx('plan.capacityRefused', {
            a: <span className="mono">{tr('capacity.example.until')}</span>,
            b: <span className="mono">{tr('capacity.example.length')}</span>,
          })}
        </p>
      ) : (
        <p className="plan-hint">
          {tx('plan.capacityHint', {
            a: <span className="mono">{tr('capacity.example.until')}</span>,
            b: <span className="mono">{tr('capacity.example.length')}</span>,
          })}
        </p>
      )}
      {meetingMinutes > 0 && (
        // Shown, never subtracted. Whether a given event is work is a judgement
        // this app does not get to make on the owner's behalf, so the collision
        // is put in front of them and the arithmetic is left alone.
        <p className="plan-hint">
          {tr('plan.meetings', { amount: fmtDuration(meetingMinutes) })}
        </p>
      )}
    </div>
  )
}

/** Step two: what goes on the day. */
function PickStep({ suggestions, colorOf, onAddTask }: {
  suggestions: SuggestGroup[]
  colorOf: (listId: string | null) => string | null
  onAddTask: (t: Task) => void
}) {
  const tr = useT()
  // Leftovers first, and reworded. The rest keep the order and the labels the
  // day itself gives them, so nothing here is a second opinion about what
  // matters — only about what to look at first.
  const leftovers = suggestions.find((g) => g.key === LEFTOVER_KEY)
  const rest = suggestions.filter((g) => g.key !== LEFTOVER_KEY)
  const groups = leftovers
    ? [{ ...leftovers, label: tr('plan.leftovers') }, ...rest]
    : rest

  if (!groups.length) {
    return (
      <div className="plan-body">
        <p className="empty">{tr('plan.nothingWaiting')}</p>
      </div>
    )
  }
  return (
    <div className="plan-body plan-scroll">
      {groups.map((g) => (
        <section key={g.key}>
          <div className="label section-label">{g.label}</div>
          <ul className="today-list">
            {g.items.map((t) => (
              <li key={taskKey(t)} className="today-row today-sug">
                <button type="button" className="today-plus"
                  aria-label={tr('plan.addToToday', { task: t.summary || tr('common.untitled') })}
                  onClick={() => onAddTask(t)}>+</button>
                <span className="today-kind-mark" data-kind="task" role="img"
                  aria-label={tr('common.task')}>
                  <span className="today-kind-box" style={colorOf(t.list)
                    ? { background: colorOf(t.list)! } : undefined} />
                </span>
                <span className="today-title" dir={textDir(t.summary)}>
                  {t.summary || tr('common.untitled')}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

/** Step three: how long each thing takes, and what order it happens in. */
function ShapeStep({ entries, renderRow }: {
  entries: DayEntry[]
  renderRow: (e: DayEntry) => ReactNode
}) {
  const tr = useT()
  if (!entries.length) {
    return (
      <div className="plan-body">
        <p className="empty">{tr('plan.nothingOnToday')}</p>
      </div>
    )
  }
  return (
    <div className="plan-body plan-scroll">
      <p className="plan-hint">{tr('plan.shapeHint')}</p>
      {/* The day's OWN rows, through the day's own renderer — so the estimate
          cell, the checkbox and the drag behave here exactly as they do behind
          this dialog, and there is no second implementation to drift. */}
      <ul className="today-list">{entries.map(renderRow)}</ul>
    </div>
  )
}
