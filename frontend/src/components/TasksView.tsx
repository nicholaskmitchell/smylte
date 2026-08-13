import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { api, uidFor, type CreateTaskBody, type List, type Task, type TaskGroup, type TasksViewMode } from '../api'
import { useTaskData } from '../data'
import {
  addDays, dayKey, fmtDue, hasZone, instantFromLocal, isOverdue, makeGuard, toLocalInput, ymd,
} from '../util'
import { AddMultipleModal, blankValues, bodyFrom, FIELDS, type RowValues } from './AddMultipleModal'
import { Sidebar } from './Sidebar'

const VIEWS: ReadonlyArray<readonly [TasksViewMode, string]> = [
  ['list', 'List'], ['day3', '3-Day'], ['week', 'Week'],
]

/** Done or won't-do — both take a task out of the active list. */
const isDone = (t: Task) => t.completed || t.cancelled

/** The shape a bare client_id has, matching the backend's `_CLIENT_ID_RE`.
 *  Only a `parent` looking exactly like this is a candidate for the legacy
 *  reinterpretation below — a real uid always carries the `@tasksd` suffix. */
const LEGACY_PARENT = /^[0-9a-f]{16,64}$/

/** A parent's subtask tally, or null when it has none to show. */
type Progress = { total: number; done: number } | null

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
const dateOut = (date: string, time: string, original: string | null | undefined) => {
  if (!date) return null
  if (!time) return date
  return hasZone(original) ? instantFromLocal(date, time) : `${date}T${time}`
}

export function TasksView({ onExpire, view, onView, sideCollapsed, onToggleSide,
  hiddenLists, onHiddenListsChange, groups, onGroupsChange,
  collapsedGroups, onCollapsedGroupsChange, showCompleted }: {
  onExpire: () => void
  view: TasksViewMode; onView: (v: TasksViewMode) => void
  sideCollapsed: boolean; onToggleSide: () => void
  hiddenLists: string[]; onHiddenListsChange: (next: string[]) => void
  groups: TaskGroup[]; onGroupsChange: (next: TaskGroup[]) => void
  collapsedGroups: string[]; onCollapsedGroupsChange: (next: string[]) => void
  showCompleted: boolean
}) {
  const guard = makeGuard(onExpire)
  // Lists, tasks and every write against them live above the tab strip, so
  // switching away and back neither drops them nor refetches from empty — and
  // Home reads the same copy rather than fanning out a second one.
  const {
    lists, tasks, listsLoaded, loaded, setLists,
    create, createMany, addSub, toggle, remove, saveDetail,
  } = useTaskData()
  const [detail, setDetail] = useState<Task | null>(null)
  // The two create surfaces, both null when closed. `adding` is the single-task
  // form; `bulk` is the multi-row composer. Each carries the list and the title
  // typed into quick-add, so text moves between them instead of being lost.
  const [adding, setAdding] = useState<{ listId: string; summary: string } | null>(null)
  const [bulk, setBulk] = useState<{ listId: string; summary: string } | null>(null)
  // A transient browsing mode (not persisted): the sidebar's "View completed"
  // button flips this to show a dedicated pane of just the completed tasks,
  // regardless of the show-completed setting.
  const [completedOnly, setCompletedOnly] = useState(false)
  // Multi-day views window from here: day3 starts on the anchor day itself,
  // week snaps to the anchor's Sunday (same week start as the calendar grid).
  const [anchor, setAnchor] = useState(() => new Date())

  // The Tasks view always merges every list into one pane, colored by list, with
  // per-list visibility toggles in the sidebar — the tasks analogue of the
  // calendar's multi-calendar grid. Every list shows until the user hides it;
  // toggling one off is an instant client-side filter (no refetch).
  const hiddenSet = useMemo(() => new Set(hiddenLists), [hiddenLists])
  const visibleLists = useMemo(() => lists.filter((l) => !hiddenSet.has(l.id)), [lists, hiddenSet])
  const colorOf = (listId: string) => lists.find((l) => l.id === listId)?.color ?? null

  // Prune settings that reference lists (or groups) that no longer exist, so a
  // deletion here or in another CalDAV client doesn't leave the blob accreting
  // stale ids. Gated on a real fetch having landed: the initial empty state
  // must not wipe prefs before the lists arrive, and neither must the cached
  // seed, which is a snapshot that may predate a list created elsewhere.
  useEffect(() => {
    if (!listsLoaded || !lists.length) return
    const ids = new Set(lists.map((l) => l.id))
    const keptHidden = hiddenLists.filter((id) => ids.has(id))
    if (keptHidden.length !== hiddenLists.length) onHiddenListsChange(keptHidden)
    let changed = false
    const prunedGroups = groups.map((g) => {
      const kept = g.lists.filter((id) => ids.has(id))
      if (kept.length !== g.lists.length) changed = true
      return { ...g, lists: kept }
    })
    if (changed) onGroupsChange(prunedGroups)
    const gids = new Set(groups.map((g) => g.id))
    const keptCollapsed = collapsedGroups.filter((id) => gids.has(id))
    if (keptCollapsed.length !== collapsedGroups.length) onCollapsedGroupsChange(keptCollapsed)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lists, listsLoaded])

  // A one-line convenience over the shared create; day columns pass a due.
  const addTask = (listId: string, summary: string, due?: string) =>
    create(listId, due ? { summary, due } : { summary })
  // Day-column drag: dropping a card on a column reschedules it to that day.
  // A timed due keeps its local time-of-day; an all-day due stays all-day.
  const [dragUid, setDragUid] = useState<string | null>(null)
  const dropOnDay = (key: string) => {
    const t = tasks.find((x) => x.uid === dragUid)
    setDragUid(null)
    if (!t) return
    if (t.due && dayKey(t.due) === key) return
    const timed = !!t.due && t.due.includes('T') && !t.due_is_date
    // Through dateOut, not a raw wall-clock string: when the DUE another CalDAV
    // client wrote is zone-anchored, sending a naive value strips its TZID and
    // moves the deadline (the backend only re-expresses a value in the original
    // zone when the incoming one is itself aware). Same reason the editor uses it.
    saveDetail(t, {
      due: timed ? dateOut(key, toLocalInput(t.due!).slice(11, 16), t.due) : key,
    })
  }

  const listApi = {
    create: (name: string) => guard(() => api.createList(name)),
    update: (id: string, body: { name?: string; color?: string | null }) =>
      guard(() => api.updateList(id, body)),
    remove: (id: string) => guard(() => api.deleteList(id)),
    reorder: (ids: string[]) => guard(() => api.reorderLists(ids)),
  }

  // Keep every fetched list in `tasks` and drop hidden ones here, so toggling a
  // list is an instant client-side filter (no refetch).
  const shownTasks = tasks.filter((t) => !hiddenSet.has(t.list))

  // One pass over every fetched task resolves both questions the rows below
  // ask: which parent a subtask really belongs to, and which children a parent
  // really has. Built from `tasks`, not `shownTasks` — hiding a list is a
  // display choice and must not change what a task's parent *is*.
  //
  // Two rules decide a match, and both mirror the server so the counts agree
  // with it exactly:
  //
  //  - The parent must sit in the same list. `_children_map` groups within one
  //    collection, so a RELATED-TO pointing across lists counts for nothing
  //    there and must count for nothing here.
  //  - A `parent` with exactly the shape of a client_id (the backend's
  //    _CLIENT_ID_RE) that names no task, while `${value}@tasksd` names one, is
  //    read as that task. Those are the subtasks written before `uidFor`
  //    existed, pointing at the create id instead of the uid derived from it.
  //    They are repaired on the wire above; this is what nests them at once,
  //    and what covers a row the repair has not reached or was refused.
  const { parentByUid, kidsByParent } = useMemo(() => {
    const byUid = new Map(tasks.map((t) => [t.uid, t] as const))
    const parents = new Map<string, string>()
    const kids = new Map<string, Task[]>()
    for (const t of tasks) {
      const raw = t.parent
      if (!raw) continue
      const p = byUid.get(raw) ?? (LEGACY_PARENT.test(raw) ? byUid.get(uidFor(raw)) : undefined)
      if (!p || p.list !== t.list) continue
      parents.set(t.uid, p.uid)
      const mine = kids.get(p.uid)
      if (mine) mine.push(t)
      else kids.set(p.uid, [t])
    }
    return { parentByUid: parents, kidsByParent: kids }
  }, [tasks])
  const parentOf = (t: Task) => parentByUid.get(t.uid) ?? null

  // Subtask progress is derived from that map rather than read off the DTO.
  // The server's child_count/completed_child_count are a snapshot of the last
  // refetch, so a subtask created or ticked just now left its parent's x/y
  // stale until an SSE bump landed a whole refetch later — while the nesting
  // beside it, already computed locally, had moved.
  const progressOf = (uid: string) => {
    const kids = kidsByParent.get(uid)
    return kids ? { total: kids.length, done: kids.filter(isDone).length } : null
  }

  const childrenOf = (uid: string) => shownTasks.filter((t) => parentOf(t) === uid)
  // A subtask reaches the DOM only underneath its own parent's row, so anything
  // whose parent isn't here has to stand on its own or it is not rendered at
  // all — invisible, and so uncompletable, uneditable and undeletable, while
  // the sidebar count still includes it. That is not a hostile-data edge case:
  // `parent` is a raw RELATED-TO UID with no existence check, another client
  // can delete a parent without cascading or point one across lists, and the
  // ordinary path is a completed parent with an open subtask while "show
  // completed" is off (the default) — the parent lands in `done`, which isn't
  // rendered, and the subtask goes with it.
  const byUid = new Map(shownTasks.map((t) => [t.uid, t] as const))
  const parentIsRendered = (t: Task) => {
    const parent = parentOf(t)
    const p = parent ? byUid.get(parent) : undefined
    return !!p && (showCompleted || !isDone(p))
  }
  const tops = shownTasks.filter((t) => !parentIsRendered(t))
  const active = tops.filter((t) => !t.completed && !t.cancelled)
  const done = tops.filter((t) => t.completed || t.cancelled)
  // Where new tasks land by default (first visible list); the list view's
  // quick-add offers a picker, day columns fall back to this.
  const defaultList = visibleLists[0]?.id ?? ''
  // Each row shows a small dot in its list's color.
  const dotFor = (t: Task) => colorOf(t.list)

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
  // The dedicated "View completed" pane: every done/cancelled top-level task
  // (respecting hidden lists via `done`), most-recent due first, undated last.
  const completedTasks = [...done].sort(byDue).reverse()
  const openOn = (key: string) =>
    shownTasks.filter((t) => !t.completed && !t.cancelled && dueDay(t) === key).sort(byDue)
  const doneOn = (key: string) =>
    shownTasks.filter((t) => (t.completed || t.cancelled) && dueDay(t) === key).sort(byDue)
  // Overdue tasks pool in the today column — but only ones due before the
  // visible window, so a task never shows both there and in its own column.
  const firstKey = ymd(days[0])
  const overdue = shownTasks
    .filter((t) => {
      const d = dueDay(t)
      return !t.completed && !t.cancelled && d !== null && d < todayKey && d < firstKey
    })
    .sort(byDue)
  const undated = shownTasks.filter((t) => !t.completed && !t.cancelled && !t.due)

  const fmtD = (d: Date) => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

  return (
    <div className="work">
      <Sidebar title="Lists" placeholder="List" items={lists}
        countOf={(l) => l.open_count} onItems={setLists} api={listApi}
        collapsed={sideCollapsed} onToggle={onToggleSide}
        hiddenIds={hiddenSet} onHiddenChange={onHiddenListsChange}
        groups={groups} onGroupsChange={onGroupsChange}
        collapsedGroups={collapsedGroups} onCollapsedGroupsChange={onCollapsedGroupsChange}
        completedActive={completedOnly} onToggleCompleted={() => setCompletedOnly((v) => !v)} />

      <div className="content">
        <div className="content-head">
          <span className="content-title">{completedOnly ? 'Completed' : 'All lists'}</span>
          <span className="content-sub">
            {completedOnly
              ? `${completedTasks.length} completed`
              : view === 'list' ? `${active.length} open` : `${fmtD(days[0])} – ${fmtD(days[span - 1])}`}
          </span>
          <span className="spacer" />
          {!completedOnly && view !== 'list' && (
            <div className="range-nav">
              <button className="icon-btn" title="Earlier" aria-label="Earlier"
                onClick={() => setAnchor(addDays(days[0], -span))}>‹</button>
              <button className="btn ghost" onClick={() => setAnchor(new Date())}>Today</button>
              <button className="icon-btn" title="Later" aria-label="Later"
                onClick={() => setAnchor(addDays(days[0], span))}>›</button>
            </div>
          )}
          {!completedOnly && (
            <div className="view-tabs" role="tablist" aria-label="Task view">
              {VIEWS.map(([v, label]) => (
                <button key={v} role="tab" aria-selected={view === v}
                  className={`view-tab ${view === v ? 'active' : ''}`}
                  onClick={() => onView(v)}>{label}</button>
              ))}
            </div>
          )}
        </div>

        {completedOnly ? (
          <div className="scroll">
            {completedTasks.length === 0 && <div className="empty">No completed tasks.</div>}
            {completedTasks.map((t) => (
              <TaskGroup key={t.uid} task={t} kids={childrenOf(t.uid)} dot={dotFor(t)}
                progress={progressOf(t.uid)} onToggle={toggle} onRemove={remove} onOpen={setDetail} onAddSub={addSub} />
            ))}
          </div>
        ) : visibleLists.length === 0 ? (
          // Three states, not two. Before a fetch has landed there is nothing
          // to say about the account: telling a user with a dozen lists to
          // "create a list to get started" was the loudest thing on screen
          // during every cold load and every tab switch.
          <div className="empty" aria-busy={!listsLoaded || undefined}>
            {!listsLoaded
              ? 'Loading…'
              : lists.length === 0
                ? 'Create a list to get started.'
                : 'Every list is hidden — toggle one on from the sidebar.'}
          </div>
        ) : view === 'list' ? (
          <>
            {defaultList && (
              <QuickAdd onSubmit={addTask}
                onExpand={(listId, summary) => setAdding({ listId, summary })}
                defaultList={defaultList} lists={visibleLists} />
            )}
            <div className="scroll">
              {active.map((t) => (
                <TaskGroup key={t.uid} task={t} kids={childrenOf(t.uid)} dot={dotFor(t)}
                  progress={progressOf(t.uid)} onToggle={toggle} onRemove={remove} onOpen={setDetail} onAddSub={addSub} />
              ))}
              {active.length === 0 && (
                <div className="empty" aria-busy={!loaded || undefined}>
                  {loaded ? 'Nothing to do here.' : 'Loading…'}
                </div>
              )}
              {showCompleted && done.length > 0 && (
                <>
                  <div className="section-label label">Completed · {done.length}</div>
                  {done.map((t) => (
                    <TaskGroup key={t.uid} task={t} kids={childrenOf(t.uid)} dot={dotFor(t)}
                      progress={progressOf(t.uid)} onToggle={toggle} onRemove={remove} onOpen={setDetail} onAddSub={addSub} />
                  ))}
                </>
              )}
            </div>
          </>
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
                    open={openOn(key)} done={showCompleted ? doneOn(key) : []}
                    overdue={key === todayKey ? overdue : []} dotOf={dotFor}
                    onToggle={toggle} onOpen={setDetail}
                    onAdd={(summary) => addTask(defaultList, summary, key)}
                    dragActive={dragUid !== null} onDropTask={() => dropOnDay(key)}
                    onDragTask={setDragUid} />
                )
              })}
            </div>
          </>
        )}
      </div>

      {detail && (
        <TaskModal task={detail} lists={visibleLists} defaultList={detail.list}
          onClose={() => setDetail(null)}
          onCreate={() => {}}
          onSave={(patch) => { saveDetail(detail, patch); setDetail(null) }}
          onDelete={() => { remove(detail); setDetail(null) }}
          onMultiple={() => {}} />
      )}

      {adding && (
        <TaskModal task={null} lists={visibleLists} defaultList={adding.listId}
          initialTitle={adding.summary}
          onClose={() => setAdding(null)}
          onCreate={create}
          onSave={() => {}}
          onDelete={() => {}}
          onMultiple={(listId, summary) => { setAdding(null); setBulk({ listId, summary }) }} />
      )}

      {bulk && (
        <AddMultipleModal lists={visibleLists} defaultList={bulk.listId}
          initialTitle={bulk.summary}
          onSubmit={createMany} onClose={() => setBulk(null)} />
      )}
    </div>
  )
}

function TaskGroup({ task, kids, dot, progress, onToggle, onRemove, onOpen, onAddSub }: {
  task: Task; kids: Task[]; dot?: string | null
  progress: Progress
  onToggle: (t: Task) => void; onRemove: (t: Task) => void
  onOpen: (t: Task) => void; onAddSub: (parent: string, summary: string) => void
}) {
  const [adding, setAdding] = useState(false)
  return (
    <div>
      <TaskRow task={task} dot={dot} progress={progress} onToggle={onToggle} onRemove={onRemove} onOpen={onOpen} onAddSub={() => setAdding(true)} />
      {kids.map((k) => (
        <TaskRow key={k.uid} task={k} sub dot={dot} onToggle={onToggle} onRemove={onRemove} onOpen={onOpen} />
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

function DayColumn({ date, isToday, open, done, overdue, dotOf, onToggle, onOpen, onAdd,
  dragActive, onDropTask, onDragTask }: {
  date: Date; isToday: boolean
  open: Task[]; done: Task[]; overdue: Task[]
  dotOf: (t: Task) => string | null | undefined
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
              <DayCard key={t.uid} task={t} showDate dot={dotOf(t)} onToggle={onToggle} onOpen={onOpen}
                onDrag={onDragTask} />
            ))}
            {open.length > 0 && <div className="col-label label">Today</div>}
          </>
        )}
        {open.map((t) => (
          <DayCard key={t.uid} task={t} dot={dotOf(t)} onToggle={onToggle} onOpen={onOpen} onDrag={onDragTask} />
        ))}
        {open.length + overdue.length + done.length === 0 && !adding && (
          <div className="col-empty">—</div>
        )}
        {done.length > 0 && (
          <>
            <div className="col-label label">Done · {done.length}</div>
            {done.map((t) => (
              <DayCard key={t.uid} task={t} dot={dotOf(t)} onToggle={onToggle} onOpen={onOpen} onDrag={onDragTask} />
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

function DayCard({ task, showDate, dot, onToggle, onOpen, onDrag }: {
  task: Task; showDate?: boolean; dot?: string | null
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
        <div className="day-card-title">
          {dot !== undefined && <span className="list-dot" style={dot ? { background: dot } : undefined} />}
          {task.summary || '(untitled)'}
        </div>
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

function TaskRow({ task, sub, dot, progress, onToggle, onRemove, onOpen, onAddSub }: {
  task: Task; sub?: boolean; dot?: string | null
  // Derived from the tasks on hand, not read off the DTO — see `progressOf`.
  // Absent for a subtask row, which never shows a count of its own.
  progress?: Progress
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
          {dot !== undefined && <span className="list-dot" style={dot ? { background: dot } : undefined} />}
          {task.summary || '(untitled)'} {task.cancelled && <span className="chip">won't do</span>}
        </div>
        {(task.due || progress || task.tags.length > 0) && (
          <div className="task-meta">
            {task.due && (
              <span className={`due ${isOverdue(task.due, task.due_is_date) && !task.completed ? 'overdue' : ''}`}>
                ◷ {fmtDue(task.due, task.due_is_date)}
              </span>
            )}
            {progress && (
              <span className="child-progress">{progress.done}/{progress.total}</span>
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

function QuickAdd({ onSubmit, onExpand, defaultList, lists }: {
  onSubmit: (listId: string, v: string) => void
  // Opens the full single-task form, carrying whatever is typed here and the
  // list selected here. Enter still creates outright — that's the fast path,
  // and the button ("New…") is the way to reach a task's other properties.
  onExpand: (listId: string, v: string) => void
  defaultList: string
  // When provided (combined view), a compact picker chooses the target list;
  // otherwise the single focused list is implied.
  lists?: List[]
}) {
  const [v, setV] = useState('')
  const [listId, setListId] = useState(defaultList)
  // Keep the target valid as the visible set changes (a hidden/deleted list
  // shouldn't stay selected); fall back to the current default.
  useEffect(() => {
    if (lists && !lists.some((l) => l.id === listId)) setListId(defaultList)
  }, [lists, defaultList, listId])
  const target = lists ? listId : defaultList
  const go = () => { if (v.trim() && target) { onSubmit(target, v.trim()); setV('') } }
  return (
    <div className="quickadd">
      <input className="input" placeholder="Add a task…" value={v}
        onChange={(e) => setV(e.target.value)}
        onKeyDown={(e: KeyboardEvent) => { if (e.key === 'Enter') go() }} />
      {lists && lists.length > 1 && (
        <select className="input quickadd-list" value={listId} title="List for the new task"
          onChange={(e) => setListId(e.target.value)}>
          {lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
      )}
      {/* Labelled with an ellipsis because it opens the form rather than
          creating outright — Enter in the field is the instant path. */}
      <button className="btn" title="Open the full form for a new task"
        onClick={() => { onExpand(target, v.trim()); setV('') }}>New…</button>
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

/**
 * The single-task form, for both creating and editing — one property table and
 * one layout, so "add a task" and "edit a task" are the same form in two modes.
 * `task === null` means creating: the list picker appears (you're choosing where
 * it lands) and the footer offers the route to the bulk composer instead of
 * Delete.
 */
function TaskModal({ task, lists, defaultList, initialTitle, onClose, onCreate, onSave, onDelete, onMultiple }: {
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
                {f.render(vals, patch, { lists, where: '', disabled: false })}
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
