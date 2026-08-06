import {
  useEffect, useRef, useState,
  type ClipboardEvent, type KeyboardEvent as ReactKeyboardEvent, type ReactNode,
} from 'react'
import { clientId, PRIORITIES, type CreateTaskBody, type List } from '../api'

// Each create is a CalDAV PUT plus a re-read GET behind a single server-side
// lock, so a batch this size is already a slow half-minute. It also bounds what
// a stray paste can do.
const MAX_ROWS = 100

export type FieldKey = 'list' | 'due' | 'start' | 'priority' | 'tags' | 'notes'

// Every property a task can carry, in raw form-control form. Shared values and
// per-row values use the same bag, so one renderer serves both and resolving a
// row is a per-key pick between the two.
export interface RowValues {
  listId: string
  dueDate: string      // yyyy-mm-dd
  dueTime: string      // HH:MM
  startDate: string    // yyyy-mm-dd
  startTime: string    // HH:MM
  priority: string     // one of PRIORITIES
  tags: string         // comma-separated, same convention as the task editor
  notes: string
}

interface Row extends RowValues {
  key: string          // stable across inserts and removals — never the index
  summary: string
}

export const blankValues = (listId: string): RowValues => ({
  listId, dueDate: '', dueTime: '', startDate: '', startTime: '', priority: 'none',
  tags: '', notes: '',
})
const blankRow = (listId: string): Row =>
  ({ ...blankValues(listId), key: clientId().slice(0, 8), summary: '' })

export interface FieldCtx { lists: List[]; where: string; disabled: boolean }

export interface FieldSpec {
  key: FieldKey
  label: string
  // The RowValues keys this field owns. Multi-slot fields switch together: a
  // shared due date implies a shared due time, since a date here and a time
  // there can't be assembled into one value.
  slots: readonly (keyof RowValues)[]
  // Used verbatim for the shared strip and for every row; `where` only varies
  // the accessible name so each control is uniquely addressable — including
  // against the toggle checkbox beside it, which is named for the property too.
  render: (v: RowValues, set: (patch: Partial<RowValues>) => void, ctx: FieldCtx) => ReactNode
}

// Distinguishes a shared control from both its own toggle and the per-row
// controls of the same property.
const FOR_ALL = ', for all tasks'

// One table drives the toggle strip, the shared controls, the column headers,
// the per-row cells — and the single-task editor in TasksView — so adding a
// property is one entry rather than an edit in five places.
export const FIELDS: readonly FieldSpec[] = [
  {
    key: 'list', label: 'List', slots: ['listId'],
    render: (v, set, { lists, where, disabled }) => (
      <select className="input" aria-label={`List${where}`} value={v.listId} disabled={disabled}
        onChange={(e) => set({ listId: e.target.value })}>
        {lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
      </select>
    ),
  },
  {
    key: 'due', label: 'Due', slots: ['dueDate', 'dueTime'],
    render: (v, set, { where, disabled }) => (
      <>
        <input className="input" type="date" aria-label={`Due date${where}`} value={v.dueDate}
          disabled={disabled} onChange={(e) => set({ dueDate: e.target.value })} />
        {/* A time with no date isn't expressible as a due, so keep the
            constraint visible rather than silently dropping the time. */}
        <input className="input" type="time" aria-label={`Due time${where}`} value={v.dueTime}
          disabled={disabled || !v.dueDate} onChange={(e) => set({ dueTime: e.target.value })} />
      </>
    ),
  },
  {
    // Two slots like Due: a task's DTSTART can be timed, and other CalDAV
    // clients routinely write one. With a date-only control the time had
    // nowhere to live and any save silently dropped it.
    key: 'start', label: 'Start', slots: ['startDate', 'startTime'],
    render: (v, set, { where, disabled }) => (
      <>
        <input className="input" type="date" aria-label={`Start date${where}`} value={v.startDate}
          disabled={disabled} onChange={(e) => set({ startDate: e.target.value })} />
        {/* A time with no date isn't expressible as a start, same as Due. */}
        <input className="input" type="time" aria-label={`Start time${where}`} value={v.startTime}
          disabled={disabled || !v.startDate} onChange={(e) => set({ startTime: e.target.value })} />
      </>
    ),
  },
  {
    key: 'priority', label: 'Priority', slots: ['priority'],
    render: (v, set, { where, disabled }) => (
      <select className="input" aria-label={`Priority${where}`} value={v.priority} disabled={disabled}
        onChange={(e) => set({ priority: e.target.value })}>
        {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
      </select>
    ),
  },
  {
    key: 'tags', label: 'Tags', slots: ['tags'],
    render: (v, set, { where, disabled }) => (
      <input className="input" aria-label={`Tags${where}`} placeholder="comma, separated"
        value={v.tags} disabled={disabled} onChange={(e) => set({ tags: e.target.value })} />
    ),
  },
  {
    key: 'notes', label: 'Notes', slots: ['notes'],
    render: (v, set, { where, disabled }) => (
      <input className="input" aria-label={`Notes${where}`} value={v.notes} disabled={disabled}
        onChange={(e) => set({ notes: e.target.value })} />
    ),
  },
]

/**
 * Split pasted text into candidate titles: one per line, trimmed, blanks
 * dropped, and the list markers you inevitably get when copying out of a doc
 * or a notes app stripped off the front.
 */
export function splitPasteLines(text: string): string[] {
  return text.split(/\r\n|\r|\n/)
    .map((s) => s.replace(/^\s*(?:[-*•–]|\d+[.)])\s+/, '').trim())
    .filter(Boolean)
}

/**
 * A row's values with every shared-ON field's slots overwritten by the shared
 * bag. The row keeps its own values for shared fields (they're just ignored),
 * so flipping a toggle back off restores exactly what was typed.
 */
export function effectiveValues(
  row: RowValues, shared: RowValues, on: Record<FieldKey, boolean>,
): RowValues {
  const out = { ...row }
  for (const f of FIELDS) if (on[f.key]) for (const s of f.slots) out[s] = shared[s]
  return out
}

/**
 * Form values → create body. Empty fields are *omitted*, never sent blank: the
 * backend only copies non-None fields onto the VTODO, so `notes: ''` would
 * write an empty DESCRIPTION instead of no description at all.
 */
export function bodyFrom(summary: string, v: RowValues): CreateTaskBody {
  const body: CreateTaskBody = { summary }
  const notes = v.notes.trim()
  if (notes) body.notes = notes
  if (v.priority && v.priority !== 'none') body.priority = v.priority
  // Same rule as the task editor: a bare date stays all-day, a date with a time
  // goes timed, and a time with no date is dropped.
  if (v.dueDate) body.due = v.dueTime ? `${v.dueDate}T${v.dueTime}` : v.dueDate
  if (v.startDate) body.start = v.startTime ? `${v.startDate}T${v.startTime}` : v.startDate
  const tags = v.tags.split(',').map((s) => s.trim()).filter(Boolean)
  if (tags.length) body.tags = tags
  return body
}

/**
 * Bulk task composer. Each property is either *shared* — set once at the top
 * and applied to every task — or per-row, in which case it becomes a column in
 * the grid. Everything starts shared, so the modal opens as title-only rows and
 * widens only for the properties the user deliberately varies.
 */
export function AddMultipleModal({ lists, defaultList, initialTitle, onSubmit, onClose }: {
  lists: List[]
  defaultList: string
  /** Carried over when the single-task form hands off to this one, so a title
   *  already typed there isn't lost in the switch. */
  initialTitle?: string
  /** Resolves to the indexes (into `items`) that failed; [] means all landed. */
  onSubmit: (
    items: Array<{ listId: string; body: CreateTaskBody }>,
    onProgress: (done: number) => void,
  ) => Promise<number[]>
  onClose: () => void
}) {
  const [rows, setRows] = useState<Row[]>(() => [
    { ...blankRow(defaultList), summary: initialTitle?.trim() || '' },
    blankRow(defaultList), blankRow(defaultList),
  ])
  const [shared, setShared] = useState<RowValues>(() => blankValues(defaultList))
  const [sharedOn, setSharedOn] = useState<Record<FieldKey, boolean>>({
    list: true, due: true, start: true, priority: true, tags: true, notes: true,
  })
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(0)
  const [failed, setFailed] = useState<string[]>([])
  const [truncated, setTruncated] = useState(false)
  const [focusKey, setFocusKey] = useState<string | null>(null)
  const titleRefs = useRef(new Map<string, HTMLInputElement>())

  // Closing mid-batch would strand a half-created run with nowhere to report
  // its failures, so every dismissal is suppressed while it's in flight.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  // Focus moves by row key, not index, so it survives inserts and removals.
  useEffect(() => {
    if (!focusKey) return
    titleRefs.current.get(focusKey)?.focus()
    setFocusKey(null)
  }, [focusKey])

  const patchRow = (key: string, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))

  const addRow = (after?: number) => {
    const row = blankRow(defaultList)
    setRows((rs) => {
      if (rs.length >= MAX_ROWS) return rs
      const next = rs.slice()
      next.splice(after === undefined ? next.length : after + 1, 0, row)
      return next
    })
    setFocusKey(row.key)
  }

  const removeRow = (key: string) =>
    // Never render an empty grid: clearing the last row beats removing it.
    setRows((rs) => (rs.length === 1 ? [blankRow(defaultList)] : rs.filter((r) => r.key !== key)))

  const live = rows.filter((r) => r.summary.trim())

  const submit = async () => {
    if (!live.length || busy) return
    setBusy(true); setDone(0); setFailed([]); setTruncated(false)
    const items = live.map((r) => {
      const v = effectiveValues(r, shared, sharedOn)
      return { listId: v.listId || defaultList, body: bodyFrom(r.summary.trim(), v) }
    })
    const bad = await onSubmit(items, setDone)
    setBusy(false)
    if (!bad.length) { onClose(); return }
    // Keep exactly what didn't land — with everything typed into it intact —
    // plus any blank rows, so the grid doesn't collapse. Retrying is safe: a
    // failed create never landed, and each attempt mints a fresh client_id.
    const badKeys = new Set(bad.map((i) => live[i].key))
    setFailed([...badKeys])
    setRows((rs) => {
      const kept = rs.filter((r) => badKeys.has(r.key) || !r.summary.trim())
      return kept.length ? kept : [blankRow(defaultList)]
    })
  }

  const onPasteTitle = (index: number) => (e: ClipboardEvent<HTMLInputElement>) => {
    const lines = splitPasteLines(e.clipboardData.getData('text/plain'))
    // A single line is an ordinary paste: let the browser place it so the caret
    // and any selection behave exactly as expected.
    if (lines.length < 2) return
    // Without this the whole blob also lands in this one controlled input.
    e.preventDefault()
    setTruncated(index + lines.length > MAX_ROWS)
    setRows((rs) => {
      // Fill forward from the pasted row, overwriting titles and appending rows
      // as needed. Only `summary` is replaced — a row's own property values
      // survive a paste over it.
      const next = rs.slice()
      lines.forEach((summary, i) => {
        const at = index + i
        if (at < next.length) next[at] = { ...next[at], summary }
        else next.push({ ...blankRow(defaultList), summary })
      })
      return next.slice(0, MAX_ROWS)
    })
  }

  const onTitleKey = (index: number, row: Row) => (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (e.metaKey || e.ctrlKey) void submit()
      else addRow(index)
      return
    }
    // Backspace on an empty title removes the row and steps back up, so a row
    // added by mistake goes away without reaching for the mouse.
    if (e.key === 'Backspace' && !row.summary && rows.length > 1) {
      e.preventDefault()
      removeRow(row.key)
      const prev = rows[index - 1] ?? rows[index + 1]
      if (prev) setFocusKey(prev.key)
    }
  }

  // Turning a property shared adopts the first value already typed into a row,
  // so "I set row 1's due date, then made due shared" doesn't silently lose it.
  const toggleShared = (f: FieldSpec) => {
    const on = !sharedOn[f.key]
    setSharedOn((s) => ({ ...s, [f.key]: on }))
    if (!on) return
    const blank = blankValues(defaultList)
    const donor = rows.find((r) => f.slots.some((s) => r[s] !== blank[s]))
    if (donor && f.slots.every((s) => shared[s] === blank[s])) {
      setShared((v) => ({ ...v, ...Object.fromEntries(f.slots.map((s) => [s, donor[s]])) }))
    }
  }

  const perRow = FIELDS.filter((f) => !sharedOn[f.key])

  return (
    // Target-checked mousedown, not a click on the overlay: with this many
    // inputs, a text drag-select that ends outside the modal would otherwise
    // close it and lose everything typed.
    <div className="overlay"
      onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose() }}>
      <div className="modal task-modal" role="dialog" aria-modal="true"
        aria-label="Add multiple tasks">
        <div className="modal-head">
          <span className="modal-title">Add multiple</span>
          <button className="icon-btn" onClick={onClose} disabled={busy} aria-label="Close">✕</button>
        </div>

        {/* A plain field with a micro-label heading, exactly like the weekly
            availability editor in Scheduling — not a panel. */}
        <div className="field">
          <label className="label">Same for all</label>
          <div className="task-props">
            {FIELDS.map((f) => (
              <div key={f.key}
                className={`task-prop prop-${f.key} ${sharedOn[f.key] ? '' : 'off'}`}>
                <label className="bulk-toggle">
                  <input type="checkbox" checked={sharedOn[f.key]} disabled={busy}
                    onChange={() => toggleShared(f)} />
                  <span>{f.label}</span>
                </label>
                {sharedOn[f.key] && (
                  <span className="task-prop-controls">
                    {f.render(shared, (p) => setShared((v) => ({ ...v, ...p })),
                      { lists, where: FOR_ALL, disabled: busy })}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="bulk-head">
          <span className="bulk-cell bulk-f-num" />
          <span className="bulk-cell bulk-f-title label">Title</span>
          {perRow.map((f) => (
            <span key={f.key} className={`bulk-cell bulk-f-${f.key} label`}>{f.label}</span>
          ))}
          <span className="bulk-x-gap" />
        </div>

        <div className="bulk-rows">
          {rows.map((row, i) => (
            <div key={row.key} className={`bulk-row ${failed.includes(row.key) ? 'failed' : ''}`}>
              <span className="bulk-cell bulk-f-num bulk-num">{i + 1}</span>
              <span className="bulk-cell bulk-f-title">
                <input className="input" value={row.summary} disabled={busy}
                  aria-label={`Title, row ${i + 1}`} placeholder="Task title"
                  autoFocus={i === 0}
                  ref={(el) => {
                    if (el) titleRefs.current.set(row.key, el)
                    else titleRefs.current.delete(row.key)
                  }}
                  onChange={(e) => patchRow(row.key, { summary: e.target.value })}
                  onPaste={onPasteTitle(i)}
                  onKeyDown={onTitleKey(i, row)} />
              </span>
              {perRow.map((f) => (
                <span key={f.key} className={`bulk-cell bulk-f-${f.key}`}>
                  {/* Carries the column name once the header row is hidden and
                      each row stacks into a card (mobile). */}
                  <span className="bulk-cell-label label">{f.label}</span>
                  {f.render(row, (p) => patchRow(row.key, p),
                    { lists, where: `, row ${i + 1}`, disabled: busy })}
                </span>
              ))}
              <button className="icon-btn bulk-x" disabled={busy}
                aria-label={`Remove row ${i + 1}`} onClick={() => removeRow(row.key)}>✕</button>
            </div>
          ))}
        </div>

        <div className="bulk-foot">
          <button className="bulk-add-row" title="Add another row"
            onClick={() => addRow()} disabled={busy || rows.length >= MAX_ROWS}>+ row</button>
          <span className="hintline">
            {truncated
              ? `Only the first ${MAX_ROWS} rows were kept.`
              : 'Paste a list of titles to fill several rows at once.'}
          </span>
        </div>

        {failed.length > 0 && (
          <div className="bulk-fail" role="alert">
            {failed.length === 1
              ? "1 task couldn't be created. Its row was kept"
              : `${failed.length} tasks couldn't be created. Their rows were kept`}
            {' '}— press Add to retry.
          </div>
        )}

        <div className="modal-actions">
          {busy && <span className="bulk-progress">{done} / {live.length}</span>}
          <span className="spacer" />
          <button className="btn" onClick={submit} disabled={busy || !live.length}>
            {busy ? 'Adding…'
              : live.length ? `Add ${live.length} ${live.length === 1 ? 'task' : 'tasks'}`
              : 'Add tasks'}
          </button>
        </div>
      </div>
    </div>
  )
}
