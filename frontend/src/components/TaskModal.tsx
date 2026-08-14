// The single-task form, lifted out of TasksView so the calendar can open it
// too. Nothing about it was TasksView's — it takes props and hands back
// callbacks — but while it lived in that file, editing a task was something
// only the tasks tab could do.
//
// `dateOut` comes with it: it is the form's own rule for what a date+time pair
// looks like on the wire, and TasksView imports it back for the day-column
// drag, which reschedules through the same rule.

import { useState, type KeyboardEvent } from 'react'
import type { CreateTaskBody, List, Task } from '../api'
import { dayKey, hasZone, instantFromLocal, toLocalInput } from '../util'
import { inputLang } from '../time'
import { useTimeFormat } from '../timeformat'
import { blankValues, bodyFrom, FIELDS, type RowValues } from './AddMultipleModal'

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
export function TaskModal({ task, lists, defaultList, initialTitle, onClose, onCreate, onSave, onDelete, onMultiple }: {
  task: Task | null
  lists: List[]
  defaultList: string
  initialTitle?: string
  onClose: () => void
  onCreate: (listId: string, body: CreateTaskBody) => void
  onSave: (patch: Record<string, unknown>) => void
  onDelete: () => void
  onMultiple: (listId: string, summary: string) => void
}) {
  const creating = task === null
  const lang = inputLang(useTimeFormat())
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
  const [start] = useState<RowValues>(initial)
  const [vals, setVals] = useState<RowValues>(start)
  // Every value here has round-tripped through a lossy form representation, so
  // resending an unchanged field rewrites a property another CalDAV client
  // authored. Compared against the opening values rather than tracked as
  // "touched": a field edited and then put back is unchanged, and sending it
  // would quantise a PRIORITY:3 the four-way picker can only render as "high".
  const same = (a: string | string[], b: string | string[]) =>
    Array.isArray(a) && Array.isArray(b)
      ? a.length === b.length && a.every((x, i) => x === b[i])
      : a === b
  const changed = (...keys: (keyof RowValues)[]) => keys.some((k) => !same(vals[k], start[k]))
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
      onCreate(listId, bodyFrom(summary.trim(), { ...vals, notes }))
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
    onSave(body)
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal task-modal" role="dialog" aria-modal="true"
        aria-label={creating ? 'Add task' : 'Task'}
        onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{creating ? 'Add task' : 'Task'}</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {/* Title and notes are the two controls FIELDS doesn't render, so they
            carry their own htmlFor/id pair — only one form is ever open. */}
        <div className="field">
          <label className="label" htmlFor="task-title">Title</label>
          <input id="task-title" className="input" value={summary} autoFocus={creating}
            onChange={(e) => setSummary(e.target.value)}
            onKeyDown={(e: KeyboardEvent) => { if (e.key === 'Enter') submit() }} />
        </div>
        <div className="task-props">
          {props.map((f) => (
            <div key={f.key} className={`task-prop prop-${f.key}`}>
              <label className="label">{f.label}</label>
              <span className="task-prop-controls">
                {f.render(vals, patch, { lists, where: '', disabled: false, lang })}
              </span>
            </div>
          ))}
        </div>
        <div className="field">
          <label className="label" htmlFor="task-notes">Notes</label>
          <textarea id="task-notes" className="input" rows={3} value={notes}
            onChange={(e) => setNotes(e.target.value)} />
        </div>
        <div className="modal-actions">
          {creating ? (
            <button className="btn ghost" onClick={() => onMultiple(listId, summary)}>
              Add multiple
            </button>
          ) : (
            <button className="btn ghost" onClick={onDelete}>Delete</button>
          )}
          <span className="spacer" />
          <button className="btn" onClick={submit} disabled={creating && !summary.trim()}>
            {creating ? 'Add' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
