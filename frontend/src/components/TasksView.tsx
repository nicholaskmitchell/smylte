import { useEffect, useState, type KeyboardEvent } from 'react'
import { api, type List, type Task } from '../api'
import { fmtDue, isOverdue, makeGuard } from '../util'
import { Sidebar } from './Sidebar'

const PRIORITIES = ['none', 'low', 'medium', 'high']

export function TasksView({ rev, onExpire }: { rev: number; onExpire: () => void }) {
  const guard = makeGuard(onExpire)
  const [lists, setLists] = useState<List[]>([])
  const [sel, setSel] = useState('')
  const [tasks, setTasks] = useState<Task[]>([])
  const [detail, setDetail] = useState<Task | null>(null)

  useEffect(() => {
    guard(async () => {
      const ls = await api.lists()
      setLists(ls)
      setSel((s) => s || ls[0]?.id || '')
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rev])

  useEffect(() => {
    if (!sel) { setTasks([]); return }
    guard(async () => setTasks(await api.tasks(sel)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, rev])

  const reload = () => guard(async () => { const ts = await api.tasks(sel); if (ts) setTasks(ts) })
  const addTask = async (summary: string) => { await guard(() => api.createTask(sel, { summary })); reload() }
  const toggle = async (t: Task) => { await guard(() => api.complete(sel, t.uid, !t.completed)); reload() }
  const remove = async (t: Task) => { await guard(() => api.deleteTask(sel, t.uid)); reload() }
  const addSub = async (parent: string, summary: string) => {
    await guard(() => api.createTask(sel, { summary, parent })); reload()
  }
  const saveDetail = async (uid: string, patch: Record<string, unknown>) => {
    await guard(() => api.patchTask(sel, uid, patch)); reload()
  }
  const listApi = {
    create: (name: string) => guard(() => api.createList(name)),
    update: (id: string, body: { name?: string; color?: string | null }) =>
      guard(() => api.updateList(id, body)),
    remove: (id: string) => guard(() => api.deleteList(id)),
    reorder: (ids: string[]) => guard(() => api.reorderLists(ids)),
  }

  const tops = tasks.filter((t) => !t.parent)
  const childrenOf = (uid: string) => tasks.filter((t) => t.parent === uid)
  const active = tops.filter((t) => !t.completed && !t.cancelled)
  const done = tops.filter((t) => t.completed || t.cancelled)
  const cur = lists.find((l) => l.id === sel)

  return (
    <div className="work">
      <Sidebar title="Lists" placeholder="List" items={lists} sel={sel}
        countOf={(l) => l.open_count} onSelect={setSel} onItems={setLists} api={listApi} />

      <div className="content">
        <div className="content-head">
          {cur?.color && <span className="title-dot" style={{ background: cur.color }} />}
          <span className="content-title">{cur ? cur.name : 'Tasks'}</span>
          <span className="content-sub">{active.length} open</span>
        </div>
        {sel && <QuickAdd onSubmit={addTask} />}
        <div className="scroll">
          {active.map((t) => (
            <TaskGroup key={t.uid} task={t} kids={childrenOf(t.uid)}
              onToggle={toggle} onRemove={remove} onOpen={setDetail} onAddSub={addSub} />
          ))}
          {active.length === 0 && sel && <div className="empty">Nothing to do here.</div>}
          {done.length > 0 && (
            <>
              <div className="section-label label">Completed · {done.length}</div>
              {done.map((t) => (
                <TaskGroup key={t.uid} task={t} kids={childrenOf(t.uid)}
                  onToggle={toggle} onRemove={remove} onOpen={setDetail} onAddSub={addSub} />
              ))}
            </>
          )}
        </div>
      </div>

      {detail && (
        <TaskDetail task={detail} onClose={() => setDetail(null)}
          onSave={(patch) => { saveDetail(detail.uid, patch); setDetail(null) }}
          onDelete={() => { remove(detail); setDetail(null) }} />
      )}
    </div>
  )
}

function TaskGroup({ task, kids, onToggle, onRemove, onOpen, onAddSub }: {
  task: Task; kids: Task[]
  onToggle: (t: Task) => void; onRemove: (t: Task) => void
  onOpen: (t: Task) => void; onAddSub: (parent: string, summary: string) => void
}) {
  const [adding, setAdding] = useState(false)
  return (
    <div>
      <TaskRow task={task} onToggle={onToggle} onRemove={onRemove} onOpen={onOpen} onAddSub={() => setAdding(true)} />
      {kids.map((k) => (
        <TaskRow key={k.uid} task={k} sub onToggle={onToggle} onRemove={onRemove} onOpen={onOpen} />
      ))}
      {adding && (
        <div className="task sub">
          <InlineCreate placeholder="Subtask" grow
            onSubmit={(v) => { onAddSub(task.uid, v); setAdding(false) }}
            onCancel={() => setAdding(false)} />
        </div>
      )}
    </div>
  )
}

function TaskRow({ task, sub, onToggle, onRemove, onOpen, onAddSub }: {
  task: Task; sub?: boolean
  onToggle: (t: Task) => void; onRemove: (t: Task) => void
  onOpen: (t: Task) => void; onAddSub?: () => void
}) {
  const pri = task.priority_label
  const priClass = pri === 'high' ? 'pri-high' : pri === 'medium' ? 'pri-med' : pri === 'low' ? 'pri-low' : ''
  return (
    <div className={`task ${sub ? 'sub' : ''} ${task.completed || task.cancelled ? 'done' : ''}`}>
      <div className={`pri-bar ${priClass}`} />
      <button className={`check ${task.completed ? 'on' : ''}`} title="Toggle complete"
        onClick={() => onToggle(task)}>✓</button>
      <div className="task-body" style={{ cursor: 'pointer' }} onClick={() => onOpen(task)}>
        <div className="task-title">
          {task.summary || '(untitled)'} {task.cancelled && <span className="chip">won't do</span>}
        </div>
        {(task.due || task.child_count > 0 || task.tags.length > 0) && (
          <div className="task-meta">
            {task.due && (
              <span className={`due ${isOverdue(task.due) && !task.completed ? 'overdue' : ''}`}>
                ◷ {fmtDue(task.due, task.due_is_date)}
              </span>
            )}
            {task.child_count > 0 && (
              <span className="child-progress">{task.completed_child_count}/{task.child_count}</span>
            )}
            {task.tags.map((tg) => <span key={tg} className="chip">#{tg}</span>)}
          </div>
        )}
      </div>
      <div className="task-actions">
        {!sub && onAddSub && <button onClick={onAddSub} title="Add subtask">+ sub</button>}
        <button className="danger" onClick={() => onRemove(task)} title="Delete">del</button>
      </div>
    </div>
  )
}

function QuickAdd({ onSubmit }: { onSubmit: (v: string) => void }) {
  const [v, setV] = useState('')
  const go = () => { if (v.trim()) { onSubmit(v.trim()); setV('') } }
  return (
    <div className="quickadd">
      <input className="input" placeholder="Add a task…" value={v}
        onChange={(e) => setV(e.target.value)}
        onKeyDown={(e: KeyboardEvent) => { if (e.key === 'Enter') go() }} />
      <button className="btn" onClick={go}>Add</button>
    </div>
  )
}

function InlineCreate({ placeholder, onSubmit, onCancel, grow }: {
  placeholder: string; onSubmit: (v: string) => void; onCancel: () => void; grow?: boolean
}) {
  const [v, setV] = useState('')
  return (
    <div className={grow ? '' : 'side-add'} style={grow ? { flex: 1 } : undefined}>
      <input className="input" autoFocus placeholder={placeholder} value={v}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => { if (!v.trim()) onCancel() }}
        onKeyDown={(e: KeyboardEvent) => {
          if (e.key === 'Enter' && v.trim()) onSubmit(v.trim())
          if (e.key === 'Escape') onCancel()
        }} />
    </div>
  )
}

function TaskDetail({ task, onClose, onSave, onDelete }: {
  task: Task; onClose: () => void
  onSave: (patch: Record<string, unknown>) => void; onDelete: () => void
}) {
  const [summary, setSummary] = useState(task.summary || '')
  const [notes, setNotes] = useState(task.notes || '')
  const [priority, setPriority] = useState(task.priority_label)
  const initDue = task.due ? (task.due.includes('T') ? task.due.slice(0, 16) : `${task.due}T00:00`) : ''
  const [due, setDue] = useState(initDue)
  const [tags, setTags] = useState(task.tags.join(', '))

  const save = () => onSave({
    summary,
    notes,
    priority,
    due: due || null,
    tags: tags.split(',').map((s) => s.trim()).filter(Boolean),
  })

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">Task</span>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>
        <div className="field">
          <label className="label">Title</label>
          <input className="input" value={summary} onChange={(e) => setSummary(e.target.value)} />
        </div>
        <div className="field">
          <label className="label">Notes</label>
          <textarea className="input" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
        <div className="field-row">
          <div className="field">
            <label className="label">Priority</label>
            <select className="input" value={priority} onChange={(e) => setPriority(e.target.value)}>
              {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="field">
            <label className="label">Due</label>
            <input className="input" type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} />
          </div>
        </div>
        <div className="field">
          <label className="label">Tags (comma-separated)</label>
          <input className="input" value={tags} onChange={(e) => setTags(e.target.value)} />
        </div>
        <div className="modal-actions">
          <button className="btn ghost" onClick={onDelete}>Delete</button>
          <span className="spacer" />
          <button className="btn" onClick={save}>Save</button>
        </div>
      </div>
    </div>
  )
}
