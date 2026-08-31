// The single-task form, lifted out of TasksView so the calendar can open it
// too. Nothing about it was TasksView's — it takes props and hands back
// callbacks — but while it lived in that file, editing a task was something
// only the tasks tab could do.
//
// `dateOut` comes with it: it is the form's own rule for what a date+time pair
// looks like on the wire, and TasksView imports it back for the day-column
// drag, which reschedules through the same rule.

import { useRef, useState, type KeyboardEvent } from 'react'
import { useEscape } from '../hooks'
import type { CreateTaskBody, List, Task } from '../api'
import { dayKey, hasZone, instantFromLocal, sameValue, toLocalInput } from '../util'
import { inputLang } from '../time'
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
 * `task === null` means creating: the list picker appears (you're choosing where
 * it lands) and the footer offers the route to the bulk composer instead of
 * Delete.
 */
export function TaskModal({ task, lists, defaultList, initialTitle, onClose, onCreate, onSave, onDelete, onMultiple, onReminderChange }: {
  task: Task | null
  lists: List[]
  defaultList: string
  initialTitle?: string
  onClose: () => void
  onCreate: (listId: string, body: CreateTaskBody) => void
  onSave: (patch: Record<string, unknown>) => void
  /** "Notify me N minutes before", in minutes, or -1 to clear it. Its own
   *  callback because it is not a wire property and does not belong in the
   *  PATCH body. Optional: a caller that has nowhere to put it simply does
   *  not offer the change rather than failing. */
  onReminderChange?: (minutes: number) => void
  onDelete: () => void
  onMultiple: (listId: string, summary: string) => void
}) {
  const creating = task === null
  const lang = inputLang(useTimeFormat(), useI18n().lang)
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

  // The list picker only makes sense while creating: moving an existing task
  // between lists means moving it between CalDAV collections, which PATCH
  // doesn't do. Notes keeps its full-width textarea either way — the composer's
  // one-line notes input is a density concession a single-task form needn't make.
  const props = FIELDS.filter((f) => f.key !== 'notes' && (creating || f.key !== 'list'))
  const listId = vals.listId || defaultList

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
    // -1 rather than null: 0 is a real lead ("tell me at the moment itself"),
    // so the clear cannot borrow falsiness. Only sent when it actually changed,
    // so an unrelated rename does not write the sidecar.
    if (reminder !== (task?.notify_minutes_before ?? null)) {
      onReminderChange?.(reminder === null ? NO_REMINDER : reminder)
    }
    onSave(body)
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
        <div className="field reminder-row">
          <label className="label" htmlFor="task-reminder">{tr('reminder.label')}</label>
          <ReminderField id="task-reminder" value={reminder} onChange={setReminder} />
        </div>
        <div className="field">
          <label className="label" htmlFor="task-notes">{tr('taskModal.notes')}</label>
          <textarea id="task-notes" className="input" rows={3} value={notes}
            onChange={(e) => setNotes(e.target.value)} />
        </div>
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
