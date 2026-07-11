import { useEffect, useMemo, useState, type KeyboardEvent } from 'react'
import { api, type List, type Task, type TasksViewMode } from '../api'
import { addDays, dayKey, fmtDue, isOverdue, makeGuard, toLocalInput, ymd } from '../util'
import { Sidebar } from './Sidebar'

const PRIORITIES = ['none', 'low', 'medium', 'high']

const VIEWS: ReadonlyArray<readonly [TasksViewMode, string]> = [
  ['list', 'List'], ['day3', '3-Day'], ['week', 'Week'],
]

export function TasksView({ rev, onExpire, view, onView, sideCollapsed, onToggleSide }: {
  rev: number; onExpire: () => void
  view: TasksViewMode; onView: (v: TasksViewMode) => void
  sideCollapsed: boolean; onToggleSide: () => void
}) {
  const guard = makeGuard(onExpire)
  const [lists, setLists] = useState<List[]>([])
  const [sel, setSel] = useState('')
  const [tasks, setTasks] = useState<Task[]>([])
  const [detail, setDetail] = useState<Task | null>(null)
  // Multi-day views window from here: day3 starts on the anchor day itself,
  // week snaps to the anchor's Sunday (same week start as the calendar grid).
  const [anchor, setAnchor] = useState(() => new Date())

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

  // Writes are optimistic: paint the change immediately, then reconcile with
  // the server's canonical DTO when it lands — or reload on failure so the UI
  // never lies. The SSE `rev` bump refetches shortly after as a safety net
  // (and fixes derived fields like a parent's subtask progress).
  const patchLocal = (uid: string, patch: Partial<Task>) =>
    setTasks((ts) => ts.map((t) => (t.uid === uid ? { ...t, ...patch } : t)))
  const settle = (dto: Task | undefined) => {
    if (dto) setTasks((ts) => ts.map((t) => (t.uid === dto.uid ? dto : t)))
    else reload()
  }

  const addTask = async (summary: string, due?: string) => {
    const t = await guard(() => api.createTask(sel, due ? { summary, due } : { summary }))
    if (t) setTasks((ts) => [...ts, t])
  }
  const toggle = async (t: Task) => {
    const done = !t.completed
    patchLocal(t.uid, { completed: done, cancelled: false, status: done ? 'COMPLETED' : 'NEEDS-ACTION' })
    settle(await guard(() => api.complete(sel, t.uid, done)))
  }
  const remove = async (t: Task) => {
    setTasks((ts) => ts.filter((x) => x.uid !== t.uid))
    if ((await guard(() => api.deleteTask(sel, t.uid))) === undefined) reload()
  }
  const addSub = async (parent: string, summary: string) => {
    const t = await guard(() => api.createTask(sel, { summary, parent }))
    if (t) setTasks((ts) => [...ts, t])
  }
  const saveDetail = async (uid: string, patch: Record<string, unknown>) => {
    const opt: Partial<Task> = {}
    if ('summary' in patch) opt.summary = patch.summary as string
    if ('notes' in patch) opt.notes = (patch.notes as string) ?? null
    if ('tags' in patch) opt.tags = patch.tags as string[]
    if ('priority' in patch) opt.priority_label = (patch.priority as string) || 'none'
    if ('due' in patch) {
      opt.due = (patch.due as string) ?? null
      opt.due_is_date = typeof patch.due === 'string' && !patch.due.includes('T')
    }
    if ('status' in patch) {
      opt.status = patch.status as string
      opt.completed = patch.status === 'COMPLETED'
      opt.cancelled = patch.status === 'CANCELLED'
    }
    patchLocal(uid, opt)
    settle(await guard(() => api.patchTask(sel, uid, patch)))
  }
  // Day-column drag: dropping a card on a column reschedules it to that day.
  // A timed due keeps its local time-of-day; an all-day due stays all-day.
  const [dragUid, setDragUid] = useState<string | null>(null)
  const dropOnDay = (key: string) => {
    const t = tasks.find((x) => x.uid === dragUid)
    setDragUid(null)
    if (!t) return
    if (t.due && dayKey(t.due) === key) return
    const timed = !!t.due && t.due.includes('T') && !t.due_is_date
    saveDetail(t.uid, { due: timed ? `${key}T${toLocalInput(t.due!).slice(11, 16)}` : key })
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

  // ---- multi-day (3-day / week) bucketing: tasks land on their due date ----
  const span = view === 'week' ? 7 : 3
  const days = useMemo(() => {
    const start = new Date(anchor)
    start.setHours(0, 0, 0, 0)
    if (view === 'week') start.setDate(start.getDate() - start.getDay())
    return Array.from({ length: span }, (_, i) => addDays(start, i))
  }, [anchor, view, span])

  const todayKey = ymd(new Date())
  const dueDay = (t: Task) => (t.due ? dayKey(t.due) : null)
  const byDue = (a: Task, b: Task) => (a.due || '').localeCompare(b.due || '')
  const openOn = (key: string) =>
    tasks.filter((t) => !t.completed && !t.cancelled && dueDay(t) === key).sort(byDue)
  const doneOn = (key: string) =>
    tasks.filter((t) => (t.completed || t.cancelled) && dueDay(t) === key).sort(byDue)
  // Overdue tasks pool in the today column — but only ones due before the
  // visible window, so a task never shows both there and in its own column.
  const firstKey = ymd(days[0])
  const overdue = tasks
    .filter((t) => {
      const d = dueDay(t)
      return !t.completed && !t.cancelled && d !== null && d < todayKey && d < firstKey
    })
    .sort(byDue)
  const undated = tasks.filter((t) => !t.completed && !t.cancelled && !t.due)

  const fmtD = (d: Date) => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

  return (
    <div className="work">
      <Sidebar title="Lists" placeholder="List" items={lists} sel={sel}
        countOf={(l) => l.open_count} onSelect={setSel} onItems={setLists} api={listApi}
        collapsed={sideCollapsed} onToggle={onToggleSide} />

      <div className="content">
        <div className="content-head">
          {cur?.color && <span className="title-dot" style={{ background: cur.color }} />}
          <span className="content-title">{cur ? cur.name : 'Tasks'}</span>
          <span className="content-sub">
            {view === 'list' ? `${active.length} open` : `${fmtD(days[0])} – ${fmtD(days[span - 1])}`}
          </span>
          <span className="spacer" />
          {view !== 'list' && (
            <div className="range-nav">
              <button className="icon-btn" title="Earlier" aria-label="Earlier"
                onClick={() => setAnchor(addDays(days[0], -span))}>‹</button>
              <button className="btn ghost" onClick={() => setAnchor(new Date())}>Today</button>
              <button className="icon-btn" title="Later" aria-label="Later"
                onClick={() => setAnchor(addDays(days[0], span))}>›</button>
            </div>
          )}
          <div className="view-tabs" role="tablist" aria-label="Task view">
            {VIEWS.map(([v, label]) => (
              <button key={v} role="tab" aria-selected={view === v}
                className={`view-tab ${view === v ? 'active' : ''}`}
                onClick={() => onView(v)}>{label}</button>
            ))}
          </div>
        </div>

        {view === 'list' ? (
          <>
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
          </>
        ) : !sel ? (
          <div className="empty">Create a list to get started.</div>
        ) : (
          <>
            {undated.length > 0 && (
              <div className="undated-hint">
                {undated.length} undated {undated.length === 1 ? 'task' : 'tasks'} not shown —{' '}
                <button onClick={() => onView('list')}>switch to List</button>
              </div>
            )}
            {/* Overdue tasks pool on today's column; when the visible window
                doesn't include today they'd silently vanish — point back. */}
            {overdue.length > 0 && !days.some((d) => ymd(d) === todayKey) && (
              <div className="undated-hint">
                {overdue.length} overdue {overdue.length === 1 ? 'task' : 'tasks'} not shown —{' '}
                <button onClick={() => setAnchor(new Date())}>jump to today</button>
              </div>
            )}
            <div className={`day-cols cols-${span}`}>
              {days.map((d) => {
                const key = ymd(d)
                return (
                  <DayColumn key={key} date={d} isToday={key === todayKey}
                    open={openOn(key)} done={doneOn(key)}
                    overdue={key === todayKey ? overdue : []}
                    onToggle={toggle} onOpen={setDetail}
                    onAdd={(summary) => addTask(summary, key)}
                    dragActive={dragUid !== null} onDropTask={() => dropOnDay(key)}
                    onDragTask={setDragUid} />
                )
              })}
            </div>
          </>
        )}
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

function DayColumn({ date, isToday, open, done, overdue, onToggle, onOpen, onAdd,
  dragActive, onDropTask, onDragTask }: {
  date: Date; isToday: boolean
  open: Task[]; done: Task[]; overdue: Task[]
  onToggle: (t: Task) => void; onOpen: (t: Task) => void
  onAdd: (summary: string) => void
  dragActive: boolean; onDropTask: () => void; onDragTask: (uid: string | null) => void
}) {
  const [adding, setAdding] = useState(false)
  // dragover bubbles up from the cards, so entering a child re-asserts `over`.
  const [over, setOver] = useState(false)
  return (
    <div className={`day-col ${isToday ? 'today' : ''} ${over && dragActive ? 'drag-over' : ''}`}
      onDragOver={(e) => { if (!dragActive) return; e.preventDefault(); setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); onDropTask() }}>
      <div className="day-col-head">
        <span className="dow">{date.toLocaleDateString(undefined, { weekday: 'short' })}</span>
        <span className="dnum">{date.getDate()}</span>
        {open.length + overdue.length > 0 && (
          <span className="count">{open.length + overdue.length}</span>
        )}
      </div>
      <div className="day-col-body">
        {overdue.length > 0 && (
          <>
            <div className="col-label label overdue">Overdue</div>
            {overdue.map((t) => (
              <DayCard key={t.uid} task={t} showDate onToggle={onToggle} onOpen={onOpen}
                onDrag={onDragTask} />
            ))}
            {open.length > 0 && <div className="col-label label">Today</div>}
          </>
        )}
        {open.map((t) => (
          <DayCard key={t.uid} task={t} onToggle={onToggle} onOpen={onOpen} onDrag={onDragTask} />
        ))}
        {open.length + overdue.length + done.length === 0 && !adding && (
          <div className="col-empty">—</div>
        )}
        {done.length > 0 && (
          <>
            <div className="col-label label">Done · {done.length}</div>
            {done.map((t) => (
              <DayCard key={t.uid} task={t} onToggle={onToggle} onOpen={onOpen} onDrag={onDragTask} />
            ))}
          </>
        )}
        {adding ? (
          <div className="day-card">
            <InlineCreate placeholder="Task" grow
              onSubmit={(v) => { onAdd(v); setAdding(false) }}
              onCancel={() => setAdding(false)} />
          </div>
        ) : (
          <button className="col-add" onClick={() => setAdding(true)}>+ Add</button>
        )}
      </div>
    </div>
  )
}

function DayCard({ task, showDate, onToggle, onOpen, onDrag }: {
  task: Task; showDate?: boolean
  onToggle: (t: Task) => void; onOpen: (t: Task) => void
  onDrag: (uid: string | null) => void
}) {
  const pri = task.priority_label
  const priClass = pri === 'high' ? 'pri-high' : pri === 'medium' ? 'pri-med' : pri === 'low' ? 'pri-low' : ''
  const done = task.completed || task.cancelled
  const timed = !!task.due && task.due.includes('T') && !task.due_is_date
  return (
    <div className={`day-card ${done ? 'done' : ''}`} draggable
      onDragStart={(e) => {
        onDrag(task.uid)
        e.dataTransfer.setData('text/plain', task.uid)  // Firefox needs data to start a drag
        e.dataTransfer.effectAllowed = 'move'
      }}
      onDragEnd={() => onDrag(null)}>
      <div className={`pri-bar ${priClass}`} />
      <button className={`check ${task.completed ? 'on' : ''}`} title="Toggle complete"
        onClick={() => onToggle(task)}>✓</button>
      <div className="day-card-body" onClick={() => onOpen(task)}>
        <div className="day-card-title">{task.summary || '(untitled)'}</div>
        {(showDate || timed || task.tags.length > 0) && (
          <div className="task-meta">
            {showDate && task.due && (
              <span className={`due ${!task.completed ? 'overdue' : ''}`}>
                ◷ {fmtDue(task.due, task.due_is_date)}
              </span>
            )}
            {!showDate && timed && (
              <span className={`due ${isOverdue(task.due, task.due_is_date) && !task.completed ? 'overdue' : ''}`}>
                {new Date(task.due!).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
              </span>
            )}
            {task.tags.map((tg) => <span key={tg} className="chip">#{tg}</span>)}
          </div>
        )}
      </div>
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
              <span className={`due ${isOverdue(task.due, task.due_is_date) && !task.completed ? 'overdue' : ''}`}>
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
  // Date and time stay separate so an all-day due survives a save as a bare
  // date instead of silently becoming a timed midnight due.
  const hasTime = !!task.due && !task.due_is_date && task.due.includes('T')
  const [dueDate, setDueDate] = useState(task.due ? dayKey(task.due) : '')
  const [dueTime, setDueTime] = useState(hasTime ? toLocalInput(task.due!).slice(11, 16) : '')
  const [tags, setTags] = useState(task.tags.join(', '))

  const save = () => onSave({
    summary,
    notes,
    priority,
    due: dueDate ? (dueTime ? `${dueDate}T${dueTime}` : dueDate) : null,
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
            <input className="input" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
          </div>
          <div className="field">
            <label className="label">Time (optional)</label>
            <input className="input" type="time" value={dueTime} onChange={(e) => setDueTime(e.target.value)} />
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
