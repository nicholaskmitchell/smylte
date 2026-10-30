// The single-task form, lifted out of TasksView so the calendar can open it
// too. Nothing about it was TasksView's — it takes props and hands back
// callbacks — but while it lived in that file, editing a task was something
// only the tasks tab could do.
//
// `dateOut` comes with it: it is the form's own rule for what a date+time pair
// looks like on the wire, and TasksView imports it back for the day-column
// drag, which reschedules through the same rule.

import { useRef, useState, type CSSProperties, type KeyboardEvent } from 'react'
import { useEscape, useSegmentThumb } from '../hooks'
import type { CreateTaskBody, List, Task } from '../api'
import {
  dayKey, hasZone, instantFromLocal, sameValue, toLocalInput, wouldRemember,
} from '../util'
import { fmtDue, inputLang } from '../time'
import { useTimeFormat } from '../timeformat'
import { blankValues, bodyFrom, FIELDS, type RowValues } from './AddMultipleModal'
import { useI18n, useT } from '../i18n'
import { NO_REMINDER, ReminderField } from './ReminderField'

/**
 * A date+time pair as the wire should carry it.
 *
 * A bare date stays all-day. A timed value is sent as a naive local string —
 * which is what the app's own writes are — *unless* the property it replaces was
 * anchored to a zone by another CalDAV client, in which case the instant goes
 * instead so the server can put it back in that zone. Sending the naive string
 * there dropped the TZID and silently moved the deadline to the viewer's
 * wall clock: `DUE;TZID=Europe/Berlin:20260810T093000` came back as
 * `DUE:20260810T033000` for a reader in New York.
 */
export const dateOut = (date: string, time: string, original: string | null | undefined) => {
  if (!date) return null
  if (!time) return date
  return hasZone(original) ? instantFromLocal(date, time) : `${date}T${time}`
}


/**
 * The single-task form, for both creating and editing — one property table and
 * one layout, so "add a task" and "edit a task" are the same form in two modes.
 * `task === null` means creating: the list picker chooses where it lands and
 * the footer offers the route to the bulk composer instead of Delete. Editing,
 * the same picker moves the task (`onSave`'s `moveTo`).
 */
export function TaskModal({ task, lists, defaultList, initialTitle, onClose, onCreate, onSave, onDelete, onMultiple, onReminderChange, onPark, onForgetOriginalDue, onDeadlineMoved }: {
  task: Task | null
  lists: List[]
  defaultList: string
  initialTitle?: string
  onClose: () => void
  onCreate: (listId: string, body: CreateTaskBody) => void
  /** `moveTo` is the list the owner picked, when it is not the one the task
   *  is in. It is not part of the PATCH: a list is a CalDAV collection, so the
   *  caller moves the task (`moveTask` in data.tsx) once the edit has landed. */
  onSave: (patch: Record<string, unknown>, moveTo?: string) => void
  /** "Notify me N minutes before", in minutes, or -1 to clear it. Its own
   *  callback because it is not a wire property and does not belong in the
   *  PATCH body. Optional: a caller that has nowhere to put it simply does
   *  not offer the change rather than failing. */
  onReminderChange?: (minutes: number) => void
  /** Set the task aside without finishing it, or bring it back. Its own
   *  callback for the reason `onReminderChange` has one — parked is app-only
   *  and does not belong in the PATCH body — and optional for the same reason
   *  too: a caller with nowhere to put it does not offer the control.
   *
   *  This is the first status-shaped affordance the editor has ever had. Won't-do
   *  sits beside it because the API has offered it since the beginning with no
   *  way to reach it from the app at all, and the two only make sense as a
   *  pair: parking is what the owner reaches for INSTEAD of cancelling, and a
   *  choice with one option visible is not a choice. */
  onPark?: (parked: boolean) => void
  /** Forget the deadline this task was moved off. Its own callback for the
   *  reason `onPark` has one — `original_due` is app-only and does not belong
   *  in the PATCH body — and optional for the same reason too: a caller with
   *  nowhere to send it simply does not offer the control, and the date is
   *  still shown.
   *
   *  Forgetting is the ONLY edit offered. The date is a record of something
   *  that happened, written once by the server when a passed deadline was
   *  rescheduled; a form field for it would let the owner type a missed
   *  deadline that never existed, and the line would stop being evidence. But
   *  it does have to be forgettable, or one badly corrected date annotates the
   *  task for good. */
  onForgetOriginalDue?: () => void
  /** Say why the REMEMBERED deadline was left: the deadline itself moved, or
   *  the owner was late. Immediate and app-only, like `onForgetOriginalDue`
   *  beside it, and optional for the same reason. A deadline this form is
   *  about to leave needs no callback: that answer rides in the PATCH as
   *  `deadline_moved`, because the record it classifies doesn't exist until
   *  the save lands. */
  onDeadlineMoved?: (moved: boolean) => void
  onDelete: () => void
  onMultiple: (listId: string, summary: string) => void
}) {
  const creating = task === null
  const { lang: uiLang, locale } = useI18n()
  const tf = useTimeFormat()
  const lang = inputLang(tf, uiLang)
  const tr = useT()
  const [summary, setSummary] = useState(task?.summary || initialTitle || '')
  const [notes, setNotes] = useState(task?.notes || '')
  // Every other property lives in the same bag the bulk composer uses, and is
  // rendered by the same FIELDS table — one form at two multiplicities. Date
  // and time stay separate slots so an all-day due survives a save as a bare
  // date instead of silently becoming a timed midnight due.
  const hasTime = !!task?.due && !task.due_is_date && task.due.includes('T')
  const startHasTime = !!task?.start && task.start.includes('T')
  const initial = (): RowValues => ({
    ...blankValues(task?.list || defaultList),
    priority: task?.priority_label ?? 'none',
    dueDate: task?.due ? dayKey(task.due) : '',
    dueTime: hasTime ? toLocalInput(task!.due!).slice(11, 16) : '',
    startDate: task?.start ? dayKey(task.start) : '',
    startTime: startHasTime ? toLocalInput(task!.start!).slice(11, 16) : '',
    tags: task?.tags ?? [],
  })
  // The reminder is not a wire property, so it is not in RowValues and does not
  // ride in the PATCH body — it has its own endpoint (api.setTaskReminder), for
  // the reason api.ts gives: a PATCH would PUT the VTODO back and move its etag,
  // making every other CalDAV client re-fetch a resource that did not change.
  const [reminder, setReminder] = useState<number | null>(task?.notify_minutes_before ?? null)
  const [start] = useState<RowValues>(initial)
  const [vals, setVals] = useState<RowValues>(start)
  // Every value here has round-tripped through a lossy form representation, so
  // resending an unchanged field rewrites a property another CalDAV client
  // authored. Compared against the opening values rather than tracked as
  // "touched": a field edited and then put back is unchanged, and sending it
  // would quantise a PRIORITY:3 the four-way picker can only render as "high".
  const changed = (...keys: (keyof RowValues)[]) =>
    keys.some((k) => !sameValue(vals[k], start[k]))
  const patch = (p: Partial<RowValues>) => setVals((v) => ({ ...v, ...p }))

  // LATE, OR DID THE DEADLINE MOVE? Asked when the date field leaves a
  // deadline that has passed, because that is when the server will remember
  // the date being left (`wouldRemember`), and the two answers record it
  // differently. Late is the default: it is the reading the app makes when
  // nobody says otherwise (the triage strip, a drag across the day columns),
  // and the one that can't quietly erase a miss.
  const leaving = !creating && wouldRemember(task) && changed('dueDate', 'dueTime')
  const [movedNow, setMovedNow] = useState(false)
  // What the block under the date field is about: the deadline this form is
  // leaving, or else the one the task already remembers. A leave wins, since
  // the server will replace a moved record with whatever this save records.
  // A remembered date equal to `due` is a deadline moved and moved back, and
  // says nothing.
  const why = creating ? null
    : leaving
      ? { iso: task.due!, isDate: task.due_is_date, moved: movedNow, saved: false }
      : task.original_due && task.original_due !== task.due
        ? { iso: task.original_due, isDate: task.original_due_is_date,
            moved: task.original_due_moved, saved: true }
        : null
  const choose = (moved: boolean) => {
    if (!why) return
    if (why.saved) onDeadlineMoved?.(moved)
    else setMovedNow(moved)
  }
  // A saved record is answered only while the date field is untouched.
  // Reclassifying it can make the edit in the field a leave (a moved record
  // gives way to the next miss), and the block would then switch to another
  // date under the click. With the date changed, the record is still shown,
  // and the field's own question, if there is one, is the one asked.
  const canAnswer = !!why && (!why.saved || (!!onDeadlineMoved && !changed('dueDate', 'dueTime')))
  const whyRef = useRef<HTMLDivElement>(null)
  useSegmentThumb(whyRef, why?.moved ? 1 : 0, canAnswer)

  // The list picker in both modes. Editing, it MOVES the task: a list is a
  // CalDAV collection and PATCH doesn't change one, so a changed list is
  // handed to the caller beside the patch rather than inside it. Notes keeps
  // its full-width textarea either way — the composer's one-line notes input
  // is a density concession a single-task form needn't make.
  const props = FIELDS.filter((f) => f.key !== 'notes')
  const listId = vals.listId || defaultList
  const moveTo = !creating && vals.listId && vals.listId !== task.list ? vals.listId : undefined

  // Creating omits empty fields (bodyFrom's rule — the backend treats a missing
  // key as "leave unset"); editing sends explicit nulls, which is how a value
  // gets cleared.
  const submit = () => {
    if (creating) {
      if (!summary.trim()) return
      const body = bodyFrom(summary.trim(), { ...vals, notes })
      // Carried in the create body rather than sent afterwards: the server
      // applies it once the uid exists, so there is no window in which the task
      // is on screen without the reminder the owner just set.
      if (reminder !== null) body.notify_minutes_before = reminder
      onCreate(listId, body)
      onClose()
      return
    }
    // Omit anything unchanged: the backend treats an absent key as "leave
    // unset", so a rename rewrites the summary and nothing else.
    const body: Record<string, unknown> = {}
    if (summary !== (task?.summary || '')) body.summary = summary
    if (notes !== (task?.notes || '')) body.notes = notes
    if (changed('priority')) body.priority = vals.priority
    if (changed('dueDate', 'dueTime')) body.due = dateOut(vals.dueDate, vals.dueTime, task?.due)
    if (changed('startDate', 'startTime')) {
      body.start = dateOut(vals.startDate, vals.startTime, task?.start)
    }
    if (changed('tags')) body.tags = vals.tags
    // Only with the date it explains, and only when it says something: false
    // is what the server assumes.
    if (leaving && movedNow) body.deadline_moved = true
    // -1 rather than null: 0 is a real lead ("tell me at the moment itself"),
    // so the clear cannot borrow falsiness. Only sent when it actually changed,
    // so an unrelated rename does not write the sidecar.
    if (reminder !== (task?.notify_minutes_before ?? null)) {
      onReminderChange?.(reminder === null ? NO_REMINDER : reminder)
    }
    onSave(body, moveTo)
  }

  // Whether the press that started this click landed on the scrim itself.
  const scrimPress = useRef(false)

  // The modal contract every other dialog in the app keeps, and the app's
  // most-used dialog was the one that did not: with `aria-modal="true"`, no
  // focus trap and no keydown listener at all, a keyboard or screen-reader user
  // had no way out of it but the mouse.
  useEscape(onClose)

  return (
    // Closes on a press AND release that both land on the scrim. A bare onClick
    // fires whenever the release lands here, so a text drag-select that began
    // inside the modal and finished outside it discarded the whole form.
    <div className="overlay"
      onMouseDown={(e) => { scrimPress.current = e.target === e.currentTarget }}
      onClick={(e) => {
        if (e.target === e.currentTarget && scrimPress.current) onClose()
        scrimPress.current = false
      }}>
      <div className="modal task-modal" role="dialog" aria-modal="true"
        aria-label={creating ? tr('taskModal.add') : tr('taskModal.edit')}
        onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{creating ? tr('taskModal.add') : tr('taskModal.edit')}</span>
          <button className="icon-btn" onClick={onClose} aria-label={tr('common.close')}>✕</button>
        </div>
        {/* Title and notes are the two controls FIELDS doesn't render, so they
            carry their own htmlFor/id pair — only one form is ever open. */}
        <div className="field">
          <label className="label" htmlFor="task-title">{tr('taskModal.title')}</label>
          <input id="task-title" className="input" value={summary} autoFocus={creating}
            onChange={(e) => setSummary(e.target.value)}
            onKeyDown={(e: KeyboardEvent) => { if (e.key === 'Enter') submit() }} />
        </div>
        <div className="task-props">
          {props.map((f) => (
            <div key={f.key} className={`task-prop prop-${f.key}`}>
              <label className="label">{tr(f.label)}</label>
              <span className="task-prop-controls">
                {/* One form, one of each control, so nothing needs telling
                    apart: the field's own name is the whole accessible name. */}
                {f.render(vals, patch,
                  { lists, disabled: false, lang, t: tr, scope: (n) => n })}
              </span>
            </div>
          ))}
        </div>
        {/* What a move takes with it, said before Save rather than found out
            after: a task's subtasks go with it, and a subtask leaves its
            parent behind (`service.move_task`). Nothing to say for a task
            that is neither. */}
        {moveTo && !creating && task.children.length > 0 && (
          <p className="hintline">{tr('taskModal.moveTakesSubtasks')}</p>
        )}
        {moveTo && !creating && task.parent && (
          <p className="hintline">{tr('taskModal.moveLeavesParent')}</p>
        )}
        {/* WHAT IT WAS PROMISED FOR, under the date field that replaced it.
            `original_due` is the deadline this task was moved off after that
            deadline had already passed — the fact rescheduling used to destroy,
            because DUE holds one value and writing a new one leaves nothing
            saying the old one was ever missed.

            A LINE, NOT A FIELD. There is no control to edit it with, on
            purpose: the server writes it once, from something that actually
            happened, and a picker here would let a missed deadline be invented.
            The only act offered is forgetting it.

            Never while creating — a task that does not exist yet has missed
            nothing — and suppressed when it matches what is in the date field,
            which is what a deadline moved and moved back looks like.

            WHY IT WAS LEFT is the one thing the owner can say about it, and
            only the owner can: a missed deadline and a deadline that moved both
            leave DUE on a new date. The pair also appears while the date field
            is leaving a passed deadline, before anything is remembered, since
            that is when the question is real (see `why` above). Answering a
            saved record is immediate, like Clear. Answering a leave goes with
            Save. */}
        {why && (
          <div className="field original-due">
            <span className="hintline">
              {tr('taskModal.originalDue', {
                date: fmtDue(why.iso, why.isDate, tf, locale),
              })}
            </span>
            {canAnswer && (
              <div className="view-tabs due-why" ref={whyRef} role="group"
                aria-label={tr('taskModal.dueWhy')}
                style={{ '--n': 2, '--i': why.moved ? 1 : 0 } as CSSProperties}>
                <button type="button" className={`view-tab ${why.moved ? '' : 'active'}`}
                  aria-pressed={!why.moved} onClick={() => choose(false)}>
                  {tr('taskModal.dueLate')}
                </button>
                <button type="button" className={`view-tab ${why.moved ? 'active' : ''}`}
                  aria-pressed={why.moved} onClick={() => choose(true)}>
                  {tr('taskModal.dueMovedChoice')}
                </button>
              </div>
            )}
            {/* A link rather than a button, the call `.linklike` exists for:
                it finishes a line of prose and a button there would read as
                this form's main action, which is Save. Only on a saved
                record: there is nothing to forget until the save lands. */}
            {why.saved && onForgetOriginalDue && (
              <button className="linklike" onClick={onForgetOriginalDue}>
                {tr('taskModal.forgetOriginalDue')}
              </button>
            )}
          </div>
        )}
        <div className="field reminder-row">
          <label className="label" htmlFor="task-reminder">{tr('reminder.label')}</label>
          <ReminderField id="task-reminder" value={reminder} onChange={setReminder} />
        </div>
        <div className="field">
          <label className="label" htmlFor="task-notes">{tr('taskModal.notes')}</label>
          <textarea id="task-notes" className="input" rows={3} value={notes}
            onChange={(e) => setNotes(e.target.value)} />
        </div>
        {/* Not while creating: neither answer means anything about a task that
            does not exist yet, and a form offering "not now" before the thing
            has been written once is asking a question with no subject. */}
        {!creating && onPark && (
          <div className="modal-actions task-lifecycle">
            <button className="btn ghost" onClick={() => onPark(!task.parked)}>
              {tr(task.parked ? 'tasks.unpark' : 'tasks.park')}
            </button>
            {!task.cancelled && (
              <button className="btn ghost"
                onClick={() => onSave({ status: 'CANCELLED' })}>
                {tr('tasks.wontDoAction')}
              </button>
            )}
            <span className="spacer" />
            <span className="hintline">
              {tr(task.parked ? 'tasks.parkedHint' : 'tasks.parkHint')}
            </span>
          </div>
        )}
        <div className="modal-actions">
          {creating ? (
            <button className="btn ghost" onClick={() => onMultiple(listId, summary)}>
              {tr('taskModal.addMultiple')}
            </button>
          ) : (
            <button className="btn ghost" onClick={onDelete}>{tr('common.delete')}</button>
          )}
          <span className="spacer" />
          <button className="btn" onClick={submit} disabled={creating && !summary.trim()}>
            {creating ? tr('common.add') : tr('common.save')}
          </button>
        </div>
      </div>
    </div>
  )
}
