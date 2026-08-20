import {
  useCallback, useEffect, useMemo, useState, type CSSProperties, type KeyboardEvent,
} from 'react'
import { api, uidFor, type CreateTaskBody, type List, type Task, type TaskGroup, type TasksViewMode } from '../api'
import { useTaskData } from '../data'
import {
  addDays, cssColor, dayKey, isOverdue, makeGuard, toLocalInput, ymd,
} from '../util'
import { fmtClock, fmtDue, inputLang } from '../time'
import { sortTasks, taskKey } from '../order'
import { useTimeFormat } from '../timeformat'
import { AddMultipleModal } from './AddMultipleModal'
import { dateOut, TaskModal } from './TaskModal'
import { Sidebar } from './Sidebar'

const VIEWS: ReadonlyArray<readonly [TasksViewMode, string]> = [
  ['list', 'List'], ['day3', '3-Day'], ['week', 'Week'],
]

/** Drag-to-reorder wiring, threaded to the list view's top-level rows.
 *  `onOver(null, from)` clears the highlight only if `from` still owns it, so a
 *  dragleave firing after the next row's dragenter doesn't blank it. */
interface ReorderDrag {
  uid: string | null
  over: string | null
  /** Which side of `over` the row will land on. The insert is deliberate —
   *  `reorder` reads the target index BEFORE removing the dragged row, so a
   *  downward drop lands AFTER the target — but the indicator drew on top
   *  regardless, so every downward drag pointed one row from where it went. */
  below: boolean
  onStart: (uid: string | null) => void
  onOver: (uid: string | null, from?: string) => void
  onDrop: (target: string) => void
}

/** Done or won't-do — both take a task out of the active list. */
const isDone = (t: Task) => t.completed || t.cancelled

/** The shape a bare client_id has, matching the backend's `_CLIENT_ID_RE`.
 *  Only a `parent` looking exactly like this is a candidate for the legacy
 *  reinterpretation below — a real uid always carries the `@tasksd` suffix. */
const LEGACY_PARENT = /^[0-9a-f]{16,64}$/

/** A parent's subtask tally, or null when it has none to show. */
type Progress = { total: number; done: number } | null

export function TasksView({ onExpire, view, onView, sideCollapsed, onToggleSide,
  hiddenLists, onHiddenListsChange, groups, onGroupsChange,
  collapsedGroups, onCollapsedGroupsChange,
  collapsedTasks, onCollapsedTasksChange, showCompleted }: {
  onExpire: () => void
  view: TasksViewMode; onView: (v: TasksViewMode) => void
  sideCollapsed: boolean; onToggleSide: () => void
  hiddenLists: string[]; onHiddenListsChange: (next: string[]) => void
  groups: TaskGroup[]; onGroupsChange: (next: TaskGroup[]) => void
  collapsedGroups: string[]; onCollapsedGroupsChange: (next: string[]) => void
  collapsedTasks: string[]; onCollapsedTasksChange: (next: string[]) => void
  showCompleted: boolean
}) {
  const guard = makeGuard(onExpire)
  // Lists, tasks and every write against them live above the tab strip, so
  // switching away and back neither drops them nor refetches from empty — and
  // Home reads the same copy rather than fanning out a second one.
  const {
    lists, serverOrderedLists, tasks, listsLoaded, listsOk, loaded, setLists,
    create, createMany, addSub, toggle, remove, saveDetail, reorder,
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
  // Indexed once, not re-scanned per row. This view fetches every list with
  // include_done=true, so `tasks` holds every completed task the account has
  // ever had — a linear `lists.find` per rendered row made the cost grow with
  // total history rather than with what is on screen.
  // Sanitised as it is indexed: `color` is whatever another CalDAV client wrote
  // into the collection's calendar-color, and it goes into an inline style.
  const colorByList = useMemo(
    () => new Map(lists.map((l) => [l.id, cssColor(l.color)] as const)), [lists])
  const colorOf = useCallback((listId: string) => colorByList.get(listId) ?? null, [colorByList])

  // Prune settings that reference lists (or groups) that no longer exist, so a
  // deletion here or in another CalDAV client doesn't leave the blob accreting
  // stale ids. Gated on a real fetch having landed: the initial empty state
  // must not wipe prefs before the lists arrive, and neither must the cached
  // seed, which is a snapshot that may predate a list created elsewhere.
  useEffect(() => {
    // `listsOk`, not `listsLoaded`: the latter is true even when the fetch
    // FAILED, so this pruned against whatever the stale disk cache held and then
    // wrote the pruned blob back — a transient 500 at startup silently and
    // permanently discarded the user's groups.
    if (!listsOk || !lists.length) return
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
  }, [lists, listsOk])

  // A one-line convenience over the shared create; day columns pass a due.
  const addTask = (listId: string, summary: string, due?: string) =>
    create(listId, due ? { summary, due } : { summary })

  // List-view drag-to-reorder. Only the list view: the day columns already own
  // the drag gesture for rescheduling (`dragUid`/`dropOnDay` below), and one
  // gesture cannot mean two things.
  const [orderUid, setOrderUid] = useState<string | null>(null)
  const [orderOver, setOrderOver] = useState<string | null>(null)
  // Indices in `sortTasks(tasks)` — the exact sequence `reorder` splices, so the
  // indicator and the insert cannot disagree. (`active` is a filtered subset and
  // is not defined until further down.)
  const orderedAll = useMemo(() => sortTasks(tasks), [tasks])
  const orderIndex = (uid: string | null) =>
    uid === null ? -1 : orderedAll.findIndex((t) => t.uid === uid)
  const reorderDrag: ReorderDrag = {
    uid: orderUid,
    over: orderOver,
    below: orderUid !== null && orderOver !== null
      && orderIndex(orderUid) >= 0 && orderIndex(orderUid) < orderIndex(orderOver),
    onStart: (uid) => { setOrderUid(uid); if (!uid) setOrderOver(null) },
    onOver: (uid, from) =>
      setOrderOver((o) => (uid === null ? (o === from ? null : o) : uid)),
    onDrop: (target) => {
      const dragged = orderUid
      setOrderUid(null)
      setOrderOver(null)
      if (dragged) void reorder(dragged, target)
    },
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
    // Through dateOut, not a raw wall-clock string: when the DUE another CalDAV
    // client wrote is zone-anchored, sending a naive value strips its TZID and
    // moves the deadline (the backend only re-expresses a value in the original
    // zone when the incoming one is itself aware). Same reason the editor uses it.
    saveDetail(t, {
      due: timed ? dateOut(key, toLocalInput(t.due!).slice(11, 16), t.due) : key,
    })
  }

  const listApi = {
    create: (name: string, color?: string | null) => guard(() => api.createList(name, color)),
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
  const rendersUnder = (t: Task) => {
    const parent = parentOf(t)
    const p = parent ? byUid.get(parent) : undefined
    return p && (showCompleted || !isDone(p)) ? p : undefined
  }
  // A RELATED-TO loop — which nothing on either side of the wire prevents —
  // leaves every task in it with a rendered parent, so a plain "no parent here"
  // test puts none of them at the top level and the whole ring disappears from
  // the pane. Walking up until the chain repeats finds the loop; its lowest uid
  // is elected the root, deterministically, so exactly one row anchors it and
  // the rest hang beneath (TaskGroup's `seen` stops the ring closing again).
  const parentIsRendered = (t: Task) => {
    const seen = new Set<string>([t.uid])
    for (let cur = rendersUnder(t); cur; cur = rendersUnder(cur)) {
      if (!seen.has(cur.uid)) { seen.add(cur.uid); continue }
      // `seen` now holds the whole ring plus the tail that led into it; only
      // the ring matters, and re-walking from `cur` collects exactly that.
      const ring: string[] = []
      for (let x: Task | undefined = cur; x && !ring.includes(x.uid); x = rendersUnder(x)) {
        ring.push(x.uid)
      }
      return t.uid !== ring.reduce((a, b) => (a < b ? a : b))
    }
    return !!rendersUnder(t)
  }
  const tops = shownTasks.filter((t) => !parentIsRendered(t))

  // Nesting goes as deep as the data does: a subtask can have subtasks of its
  // own, so the rows render as a tree rather than one parent and a flat run of
  // children. Built once here, keyed by the parent each row actually renders
  // under (so a child promoted to the top level takes its own descendants with
  // it rather than being orphaned twice over).
  const kidRows = useMemo(() => {
    const m = new Map<string, Task[]>()
    for (const t of shownTasks) {
      if (!parentIsRendered(t)) continue
      const p = parentOf(t)!
      const mine = m.get(p)
      if (mine) mine.push(t)
      else m.set(p, [t])
    }
    // Subtasks get the same order as top-level rows — they are collected in
    // array order above, which is exactly the thing that used to shuffle.
    for (const [p, kids] of m) m.set(p, sortTasks(kids))
    return m
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks, hiddenSet, showCompleted, parentByUid])
  const childrenOf = useCallback((uid: string) => kidRows.get(uid) ?? [], [kidRows])

  // Folded subtask trees. Account-synced like the sidebar's collapsed groups,
  // so a tree you tidied away stays tidy on the next load and in the next
  // browser. Only uids that still name a task with children are kept: a task
  // deleted here or in another client would otherwise leave the set growing
  // forever, and re-creating a uid is impossible anyway.
  //
  // Pruned against `kidsByParent`, which is built from ALL `tasks` and is what
  // that sentence actually describes. It used to prune against `kidRows`, which
  // is built from `shownTasks` and only for rows whose parent is RENDERED RIGHT
  // NOW — so it meant "has a child on screen this instant". Any folded tree in a
  // hidden list, or under a completed parent while the default
  // showCompleted={false} was in force, was absent from it and got dropped the
  // moment the user folded anything else. `onCollapsedTasksChange` goes straight
  // to `saveSettingsSoon({collapsed_tasks})`, so the loss was written to the
  // account, survived a reload and followed the user to another browser.
  const collapsedSet = useMemo(() => new Set(collapsedTasks), [collapsedTasks])
  const setCollapsed = useCallback((uid: string, next: boolean) => {
    if (next === collapsedSet.has(uid)) return
    const kept = collapsedTasks.filter((x) => x !== uid && kidsByParent.has(x))
    onCollapsedTasksChange(next ? [...kept, uid] : kept)
  }, [collapsedSet, collapsedTasks, kidsByParent, onCollapsedTasksChange])
  // Sorted, not just filtered. These render straight into the list view, which
  // used to show them in raw array order — so a new task appeared at the bottom
  // and then jumped when the refetch replaced the array. `compareTasks` is a
  // total order, so the array's own order stops mattering entirely.
  const active = sortTasks(tops.filter((t) => !t.completed && !t.cancelled))
  const done = sortTasks(tops.filter((t) => t.completed || t.cancelled))
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
  // The dedicated "View completed" pane: every done/cancelled top-level task
  // (respecting hidden lists via `done`), most-recent due first, undated last.
  // The dated ones are reversed; the undated are appended rather than swept
  // along, since reversing the whole run would float them to the top.
  //
  // It needs its own top-level set rather than reusing `done`. `tops` calls a
  // task top-level when its parent is not RENDERED, and `rendersUnder` consults
  // the global `showCompleted` flag — but this pane shows done tasks regardless
  // of that flag. So with the default showCompleted={false} a completed child
  // of a completed parent was promoted to a row of its own, sitting beside the
  // parent it belongs under, and the tree the pane is meant to show was flat.
  const completedTops = shownTasks.filter((t) => {
    if (!isDone(t)) return false
    const p = parentOf(t)
    const parent = p ? byUid.get(p) : undefined
    return !(parent && isDone(parent))
  })
  const completedKids = useCallback((uid: string) => {
    const kids = shownTasks.filter((t) => {
      if (!isDone(t)) return false
      const p = parentOf(t)
      return p === uid
    })
    return sortTasks(kids)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks, hiddenSet, parentByUid])
  const completedTasks = [
    ...sortTasks(completedTops.filter((t) => t.due)).reverse(),
    ...sortTasks(completedTops.filter((t) => !t.due)),
  ]
  const openOn = (key: string) =>
    sortTasks(shownTasks.filter((t) => !t.completed && !t.cancelled && dueDay(t) === key))
  const doneOn = (key: string) =>
    sortTasks(shownTasks.filter((t) => (t.completed || t.cancelled) && dueDay(t) === key))
  // Overdue tasks pool in the today column — but only ones due before the
  // visible window, so a task never shows both there and in its own column.
  const firstKey = ymd(days[0])
  const overdue = sortTasks(shownTasks.filter((t) => {
    const d = dueDay(t)
    return !t.completed && !t.cancelled && d !== null && d < todayKey && d < firstKey
  }))
  const undated = sortTasks(shownTasks.filter((t) => !t.completed && !t.cancelled && !t.due))

  const fmtD = (d: Date) => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

  return (
    <div className="work">
      {/* The raw order, not `lists`: dragging a row here PROPPATCHes
          calendar-order onto every collection in Radicale, and the grouped
          order is an app-only view that has no business rewriting what other
          CalDAV clients read. The rail looks identical either way — its group
          sections are filters, so they preserve relative order. */}
      <Sidebar title="Lists" placeholder="List" items={serverOrderedLists}
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
              <TaskGroup key={taskKey(t)} task={t} childrenOf={completedKids} dot={dotFor(t)}
                progressOf={progressOf} collapsed={collapsedSet} onCollapse={setCollapsed}
                onToggle={toggle} onRemove={remove} onOpen={setDetail} onAddSub={addSub} />
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
                <TaskGroup key={taskKey(t)} task={t} childrenOf={childrenOf} dot={dotFor(t)}
                  progressOf={progressOf} collapsed={collapsedSet} onCollapse={setCollapsed}
                  onToggle={toggle} onRemove={remove} onOpen={setDetail} onAddSub={addSub}
                  drag={reorderDrag} />
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
                    <TaskGroup key={taskKey(t)} task={t} childrenOf={childrenOf} dot={dotFor(t)}
                      progressOf={progressOf} collapsed={collapsedSet} onCollapse={setCollapsed}
                      onToggle={toggle} onRemove={remove} onOpen={setDetail} onAddSub={addSub} />
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

/** How far in a row may be indented before the titles have nowhere left to go.
 *  Deeper tasks still render, they just stop stepping right. */
const MAX_INDENT = 6

/**
 * One task and everything beneath it.
 *
 * Recursive, because a subtask can have subtasks of its own — the wire has
 * always allowed it (RELATED-TO is just a UID) and the flat parent-plus-children
 * render was the only thing standing in the way. `seen` carries the ancestors on
 * the current path: RELATED-TO has no cycle check on either side of the wire, so
 * a loop authored by another client would otherwise recurse until the stack
 * gave out. A row already on its own path is dropped rather than repeated.
 */
function TaskGroup({ task, childrenOf, dot, progressOf, depth = 0, seen,
  collapsed, onCollapse, onToggle, onRemove, onOpen, onAddSub, drag }: {
  task: Task
  childrenOf: (uid: string) => Task[]
  dot?: string | null
  progressOf: (uid: string) => Progress
  depth?: number
  seen?: ReadonlySet<string>
  collapsed: ReadonlySet<string>
  onCollapse: (uid: string, next: boolean) => void
  onToggle: (t: Task) => void; onRemove: (t: Task) => void
  onOpen: (t: Task) => void; onAddSub: (parent: string, summary: string) => void
  /** Manual reorder, list view only (opt-in). Wraps the whole subtree, not just
   *  the row, so a parent takes its subtasks with it. Subtasks are not
   *  themselves reorderable — they render under their parent wherever it goes. */
  drag?: ReorderDrag
}) {
  const [adding, setAdding] = useState(false)
  const kids = childrenOf(task.uid).filter((k) => !seen?.has(k.uid))
  const isCollapsed = collapsed.has(task.uid)
  const path = useMemo(() => new Set([...(seen ?? []), task.uid]), [seen, task.uid])
  const indent = Math.min(depth, MAX_INDENT)
  return (
    <div
      className={drag
        ? `task-drag ${drag.over === task.uid && drag.uid !== task.uid
            ? (drag.below ? 'drag-over drag-below' : 'drag-over') : ''}`
        : undefined}
      draggable={!!drag}
      onDragStart={drag && ((e) => {
        // `draggable` is on the row wrapper, so a press inside the nested inline
        // "add subtask" field started a drag of the PARENT task — selecting text
        // there silently reordered the list. A gesture that begins on something
        // interactive belongs to that control.
        if ((e.target as HTMLElement)?.closest?.('input, textarea, button, [contenteditable]')) {
          e.preventDefault()
          return
        }
        drag.onStart(task.uid)
        e.dataTransfer.effectAllowed = 'move'
        // Firefox refuses to start a drag with nothing on the transfer.
        e.dataTransfer.setData('text/plain', task.uid)
      })}
      onDragOver={drag && ((e) => { e.preventDefault(); drag.onOver(task.uid) })}
      onDragLeave={drag && (() => drag.onOver(null, task.uid))}
      onDrop={drag && ((e) => { e.preventDefault(); drag.onDrop(task.uid) })}
      onDragEnd={drag && (() => drag.onStart(null))}>
      <TaskRow task={task} dot={dot} depth={indent} progress={progressOf(task.uid)}
        collapsed={kids.length > 0 ? isCollapsed : undefined}
        onCollapse={(next) => onCollapse(task.uid, next)}
        onToggle={onToggle} onRemove={onRemove} onOpen={onOpen}
        onAddSub={() => { onCollapse(task.uid, false); setAdding(true) }} />
      {!isCollapsed && kids.map((k) => (
        <TaskGroup key={taskKey(k)} task={k} childrenOf={childrenOf} dot={dot}
          progressOf={progressOf} depth={depth + 1} seen={path}
          collapsed={collapsed} onCollapse={onCollapse}
          onToggle={onToggle} onRemove={onRemove} onOpen={onOpen} onAddSub={onAddSub} />
      ))}
      {!isCollapsed && adding && (
        <div className="task" style={indentStyle(indent + 1)}>
          <InlineCreate placeholder="Subtask" grow
            onSubmit={(v) => { onAddSub(task.uid, v); setAdding(false) }}
            onCancel={() => setAdding(false)} />
        </div>
      )}
    </div>
  )
}

/** Indent a row by its depth in the tree. Level 0 keeps the pane's own gutter. */
const indentStyle = (depth: number) =>
  (depth > 0 ? { '--task-depth': depth } as CSSProperties : undefined)

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
              <DayCard key={taskKey(t)} task={t} showDate dot={dotOf(t)} onToggle={onToggle} onOpen={onOpen}
                onDrag={onDragTask} />
            ))}
            {open.length > 0 && <div className="col-label label">Today</div>}
          </>
        )}
        {open.map((t) => (
          <DayCard key={taskKey(t)} task={t} dot={dotOf(t)} onToggle={onToggle} onOpen={onOpen} onDrag={onDragTask} />
        ))}
        {open.length + overdue.length + done.length === 0 && !adding && (
          <div className="col-empty">—</div>
        )}
        {done.length > 0 && (
          <>
            <div className="col-label label">Done · {done.length}</div>
            {done.map((t) => (
              <DayCard key={taskKey(t)} task={t} dot={dotOf(t)} onToggle={onToggle} onOpen={onOpen} onDrag={onDragTask} />
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
  const tf = useTimeFormat()
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
                ◷ {fmtDue(task.due, task.due_is_date, tf)}
              </span>
            )}
            {!showDate && timed && (
              <span className={`due ${isOverdue(task.due, task.due_is_date) && !task.completed ? 'overdue' : ''}`}>
                {fmtClock(task.due!, tf)}
              </span>
            )}
            {task.tags.map((tg) => <span key={tg} className="chip">#{tg}</span>)}
          </div>
        )}
      </div>
    </div>
  )
}

function TaskRow({ task, depth = 0, dot, progress, collapsed, onCollapse,
  onToggle, onRemove, onOpen, onAddSub }: {
  task: Task
  /** Depth in the tree; 0 is a top-level row. Drives the indent only. */
  depth?: number
  dot?: string | null
  // Derived from the tasks on hand, not read off the DTO — see `progressOf`.
  progress?: Progress
  /** Undefined when the row has no children to hide. */
  collapsed?: boolean
  onCollapse?: (next: boolean) => void
  onToggle: (t: Task) => void; onRemove: (t: Task) => void
  onOpen: (t: Task) => void; onAddSub?: () => void
}) {
  const pri = task.priority_label
  const priClass = pri === 'high' ? 'pri-high' : pri === 'medium' ? 'pri-med' : pri === 'low' ? 'pri-low' : ''
  const label = task.summary || '(untitled)'
  const tf = useTimeFormat()
  return (
    <div className={`task ${depth > 0 ? 'sub' : ''} ${task.completed || task.cancelled ? 'done' : ''}`}
      style={indentStyle(depth)}>
      <div className={`pri-bar ${priClass}`} />
      {/* The twisty holds its column whether or not the row has children, so a
          tree of mixed rows keeps one straight edge down the left. */}
      {collapsed === undefined ? <span className="twisty-gap" /> : (
        <button className={`twisty ${collapsed ? '' : 'open'}`}
          aria-expanded={!collapsed}
          title={collapsed ? `Show subtasks of ${label}` : `Hide subtasks of ${label}`}
          aria-label={collapsed ? `Show subtasks of ${label}` : `Hide subtasks of ${label}`}
          onClick={() => onCollapse?.(!collapsed)}>›</button>
      )}
      <button className={`check ${task.completed ? 'on' : ''}`} title="Toggle complete"
        onClick={() => onToggle(task)}>✓</button>
      <div className="task-body" style={{ cursor: 'pointer' }} onClick={() => onOpen(task)}>
        <div className="task-title">
          {dot !== undefined && <span className="list-dot" style={dot ? { background: dot } : undefined} />}
          {label} {task.cancelled && <span className="chip">won't do</span>}
        </div>
        {(task.due || progress || task.tags.length > 0) && (
          <div className="task-meta">
            {task.due && (
              <span className={`due ${isOverdue(task.due, task.due_is_date) && !task.completed ? 'overdue' : ''}`}>
                ◷ {fmtDue(task.due, task.due_is_date, tf)}
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
        {onAddSub && <button onClick={onAddSub} title="Add subtask">+ sub</button>}
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
