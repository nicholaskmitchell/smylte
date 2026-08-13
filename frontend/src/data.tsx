// The account's task and calendar data, held once above the tab strip.
//
// It used to live inside each view, which meant switching tabs unmounted it and
// every navigation refetched from an empty array — the same four-hop waterfall
// as a cold boot, complete with "Create a list to get started." flashing at a
// user who has a dozen. Home fetched its own second copy of every task on top,
// through a read-only hook whose `loading` flag never cleared on the error path,
// so one failed request left every dashboard module blank for good.
//
// Holding it here fixes all three at once: one fetch serves both views, the data
// survives a tab switch, and `cache.ts` mirrors it to disk so a cold load paints
// what the user last saw instead of nothing.
//
// A context rather than props because the three views already take eight props
// apiece; this way their signatures — and their tests — stay about what they
// render.

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ReactNode,
} from 'react'
import {
  api, AuthError, clientId, uidFor,
  type CalEvent, type CreateTaskBody, type List, type Task, type TaskGroup,
} from './api'
import { orderLists } from './lists'
import {
  cacheCalendars, cacheEvents, cacheLists, cacheTasks,
  readCachedCalendars, readCachedEvents, readCachedLists, readCachedTasks,
} from './cache'
import { makeGuard } from './util'

/** The shape a bare client_id has, matching the backend's `_CLIENT_ID_RE`. */
const LEGACY_PARENT = /^[0-9a-f]{16,64}$/

/** How long after a change the mirror is written. One drag, one write. */
const CACHE_DEBOUNCE_MS = 400

export interface TaskData {
  /** In the order the sidebar shows them — group by group, then ungrouped.
   *  This is what every list picker should render: the dropdowns used to show
   *  the raw fetch order, which stops matching the sidebar the moment a group
   *  exists, so the picker followed an order nobody can see. */
  lists: List[]
  /** As the server sorted them, for the one caller that must not use the other.
   *  The sidebar's drag-reorder PROPPATCHes `calendar-order` onto every
   *  collection in Radicale, and task groups are an app-only construct with
   *  nowhere to live on the wire — handing it the grouped array would write
   *  this app's grouping into shared CalDAV state, reordering the collections
   *  for Tasks.org, jtx Board and Thunderbird to match something none of them
   *  can see. A display preference does not get to rewrite that. */
  serverOrderedLists: List[]
  tasks: Task[]
  /** The lists fetch has returned at least once this session. Cached rows are
   *  worth painting but are not evidence about the account, so "create a list
   *  to get started" — and pruning settings that name a list — wait on this. */
  listsLoaded: boolean
  /** …and the tasks behind them have landed too. Kept separate because the
   *  lists arrive a hop earlier, and "nothing to do here" said in that gap is
   *  just as wrong as saying the account has no lists. */
  loaded: boolean
  setLists: (next: List[]) => void
  create: (listId: string, body: CreateTaskBody,
    after?: Promise<Task | undefined>) => Promise<Task | undefined>
  createMany: (items: Array<{ listId: string; body: CreateTaskBody; cid: string }>,
    onProgress: (done: number) => void) => Promise<number[]>
  addSub: (parent: string, summary: string) => void
  toggle: (t: Task) => Promise<void>
  remove: (t: Task) => Promise<void>
  saveDetail: (t: Task, patch: Record<string, unknown>) => Promise<void>
}

export interface CalendarData {
  cals: List[]
  loaded: boolean
  setCals: (next: List[]) => void
  /** Events for a window, from whatever is on hand — a previous fetch this
   *  session, or the disk mirror. Empty while genuinely unknown. */
  eventsFor: (from: string, to: string) => CalEvent[]
  /** Ask for a window. Idempotent per (from, to, rev, calendars). */
  requestWindow: (from: string, to: string, cals: List[]) => void
  setEvents: (from: string, to: string, next: (prev: CalEvent[]) => CalEvent[]) => void
  reload: (from: string, to: string, cals: List[]) => void
}

const TaskCtx = createContext<TaskData | null>(null)
const CalendarCtx = createContext<CalendarData | null>(null)

export function useTaskData(): TaskData {
  const v = useContext(TaskCtx)
  if (!v) throw new Error('useTaskData outside DataProvider')
  return v
}

export function useCalendarData(): CalendarData {
  const v = useContext(CalendarCtx)
  if (!v) throw new Error('useCalendarData outside DataProvider')
  return v
}

const windowKey = (from: string, to: string) => `${from}|${to}`

export function DataProvider({ rev, onExpire, taskGroups = [], enabled = true, children }: {
  rev: number
  onExpire: () => void
  /** The sidebar's groupings, which decide the order `lists` comes back in. */
  taskGroups?: TaskGroup[]
  /** Whether to talk to the server yet. The provider sits above the auth branch
   *  so resolving the session does not remount the whole shell underneath it —
   *  but it must not fetch while the session is unknown or gone. Cached rows
   *  still seed, so the frame after auth lands already has content. */
  enabled?: boolean
  children: ReactNode
}) {
  const expire = useRef(onExpire)
  expire.current = onExpire
  const guard = useMemo(() => makeGuard(() => expire.current()), [])

  return (
    <TaskProvider rev={rev} guard={guard} enabled={enabled} taskGroups={taskGroups}
      onExpire={() => expire.current()}>
      <CalendarProvider rev={rev} guard={guard} enabled={enabled}>{children}</CalendarProvider>
    </TaskProvider>
  )
}

type Guard = ReturnType<typeof makeGuard>

// ── tasks ───────────────────────────────────────────────────────────────────

function TaskProvider({ rev, guard, enabled, taskGroups, onExpire, children }: {
  rev: number; guard: Guard; enabled: boolean; taskGroups: TaskGroup[]
  onExpire: () => void; children: ReactNode
}) {
  // Seeded from the disk mirror so the first frame has content. The server
  // overwrites both a moment later, like every other cached thing in the app.
  const [lists, setLists] = useState<List[]>(() => readCachedLists() ?? [])
  const [tasks, setTasks] = useState<Task[]>(() => readCachedTasks() ?? [])
  const [listsLoaded, setListsLoaded] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!enabled) return
    guard(async () => {
      const ls = await api.lists()
      // A malformed body must not become the state every render maps over —
      // `guard` only shields us from a rejection, not from a 200 with junk in it.
      if (Array.isArray(ls)) setLists(ls)
    }).finally(() => setListsLoaded(true))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rev, enabled])

  // In-flight task fetches carry a token: a response commits only while its
  // token is still the newest and the view it was issued for (`loadKey`) is
  // still current, so an out-of-order response can never clobber a later fetch.
  // Writes bump the token too, so a refetch whose snapshot predates an
  // optimistic paint is dropped instead of wiping it (the mutation's own SSE
  // `rev` bump refetches again once the server has published the change).
  // Every list is fetched and hidden ones filtered at render, so a visibility
  // toggle is instant (no refetch) — exactly like the calendar grid.
  const loadKey = `*|${lists.map((l) => l.id).join(',')}`
  const keyRef = useRef(loadKey)
  keyRef.current = loadKey
  const fetchToken = useRef(0)
  const invalidateFetches = () => { fetchToken.current += 1 }

  // Waits for the real lists rather than fanning out over the cached ones: a
  // seeded id may name a list deleted in another client, and a 404 per stale
  // list would raise a toast apiece. The cache is already painting meanwhile,
  // so the extra hop costs nothing on screen.
  useEffect(() => {
    if (!enabled || !listsLoaded) return
    if (lists.length === 0) {
      setTasks([])
      setLoaded(true)
      return
    }
    const token = ++fetchToken.current
    const key = loadKey
    guard(async () => {
      const per = await Promise.all(lists.map((l) => api.tasks(l.id)))
      const ts = per.filter(Array.isArray).flat()
      if (token === fetchToken.current && key === keyRef.current) setTasks(ts)
    }).finally(() => setLoaded(true))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadKey, rev, enabled, listsLoaded])

  // Mirror to disk on the trailing edge, so a burst of optimistic paints costs
  // one write rather than one per keystroke. Writing on the optimistic paint
  // too is deliberate: reloading straight after adding a task should show it.
  useEffect(() => {
    if (!loaded) return          // never persist the pre-fetch seed back over itself
    const t = setTimeout(() => { cacheLists(lists); cacheTasks(tasks) }, CACHE_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [lists, tasks, loaded])

  // Writes are optimistic: paint the change immediately, then reconcile with
  // the server's canonical DTO when it lands — or roll the touched task back
  // on failure (the guard has already raised the error toast) so the UI never
  // lies. The SSE `rev` bump refetches shortly after as a safety net. Rollbacks
  // restore only the affected task — never a whole-array snapshot, which would
  // clobber interleaved changes to other tasks.
  const patchLocal = (uid: string, patch: Partial<Task>) =>
    setTasks((ts) => ts.map((t) => (t.uid === uid ? { ...t, ...patch } : t)))
  const settle = (dto: Task | undefined, orig: Task) =>
    setTasks((ts) => ts.map((t) => (t.uid === orig.uid ? (dto ?? orig) : t)))

  // A pending create renders immediately as a local stand-in carrying the uid
  // the server *will* give it (`uidFor`, from the same client_id the request
  // sends), so success can swap in the server DTO — and failure remove it — by
  // uid. The stand-in used to wear the bare client_id instead, which made every
  // write issued against the row before it settled name a resource that did not
  // exist: completing it 404'd, and a subtask added to it wrote a RELATED-TO
  // pointing at nothing, orphaning the child in CalDAV for good.
  // Every task carries its own list id (`list`), so writes below target the
  // task's own list rather than a single "selected" one — essential once the
  // combined view mixes tasks from several lists.
  const draftTask = (uid: string, listId: string, body: CreateTaskBody): Task => ({
    uid, list: listId, summary: body.summary, notes: body.notes ?? null, status: 'NEEDS-ACTION',
    completed: false, cancelled: false,
    // `priority` is the numeric iCal field the server derives; the rows render
    // `priority_label`, so the stand-in paints the right stripe right away and
    // the server's DTO fills the number in when it lands.
    priority: null, priority_label: body.priority || 'none',
    percent_complete: null, due: body.due ?? null,
    due_is_date: !!body.due && !body.due.includes('T'),
    start: body.start ?? null, tags: body.tags ?? [], parent: body.parent ?? null, children: [],
    child_count: 0, completed_child_count: 0, derived_percent: null,
    pinned: false, href: '', etag: '',
  })

  // Swap a settled server DTO in for its stand-in, in place. `key` is the
  // loadKey the create was issued under — the lists may have changed mid-flight.
  // Since the stand-in already carries the DTO's uid, a refetch that landed
  // between the paint and the settle can have brought the real task in
  // alongside it; collapse both onto one row rather than mapping each to the
  // DTO, which would leave two identical rows fighting over one React key.
  const settleCreate = (uid: string, key: string, t: Task) => {
    const here = key === keyRef.current
    setTasks((ts) => {
      let placed = false
      const next: Task[] = []
      for (const x of ts) {
        if (x.uid !== uid && x.uid !== t.uid) { next.push(x); continue }
        if (placed) continue
        placed = true
        next.push(t)
      }
      // Stand-in already gone and no twin to replace — the lists changed under
      // it. Append only when it still belongs here.
      if (!placed && here) next.push(t)
      return next
    })
  }

  // Creates still in flight, keyed by the uid their stand-in already carries.
  // A subtask waits on its parent's entry before its own request goes out:
  // RELATED-TO is written verbatim with no existence check, so a child whose
  // parent never lands would be orphaned in the CalDAV data rather than merely
  // mispainted. The UI only offers "+ sub" on top-level rows, so the chain is
  // one deep today; nothing here assumes that.
  const pending = useRef(new Map<string, Promise<Task | undefined>>())

  const create = async (listId: string, body: CreateTaskBody,
    after?: Promise<Task | undefined>): Promise<Task | undefined> => {
    if (!listId) return undefined
    const cid = clientId()
    const uid = uidFor(cid)
    const key = loadKey
    invalidateFetches()
    setTasks((ts) => [...ts, draftTask(uid, listId, body)])
    const settled = (async () => {
      // Awaited after the paint, never before it — the point of the whole
      // exercise is that the subtask appears the instant it is typed.
      if (after && !(await after)) {
        setTasks((ts) => ts.filter((x) => x.uid !== uid))
        return undefined
      }
      invalidateFetches()          // a refetch may have started while we waited
      const t = await guard(() => api.createTask(listId, { ...body, client_id: cid }))
      if (!t) { setTasks((ts) => ts.filter((x) => x.uid !== uid)); return undefined }
      settleCreate(uid, key, t)
      return t
    })()
    pending.current.set(uid, settled)
    void settled.finally(() => {
      if (pending.current.get(uid) === settled) pending.current.delete(uid)
    })
    return settled
  }

  // Create many tasks in one go, for the "Add multiple" composer: one optimistic
  // paint for the whole batch, then one request per task, in order.
  //
  // Sequential on purpose. TaskService holds a single lock around every engine
  // call and each create is a CalDAV PUT plus a re-read GET, so parallel POSTs
  // would queue server-side anyway; going one at a time costs nothing and buys
  // an honest progress count, per-row failure attribution, and a clean stop when
  // the session expires mid-batch.
  //
  // Deliberately bypasses `guard`: a nine-row batch that fails would raise nine
  // toasts. Failures come back as indexes instead and the modal reports them in
  // place, against the rows that produced them.
  const createMany = async (
    items: Array<{ listId: string; body: CreateTaskBody; cid: string }>,
    onProgress: (done: number) => void,
  ): Promise<number[]> => {
    const key = loadKey
    // The ids come from the rows, which keep them across a retry. Minting them
    // here meant every attempt carried a new idempotency slug, so a create whose
    // response was lost on the way back — the failure the composer explicitly
    // invites you to retry — landed a second time as a distinct task.
    const cids = items.map((it) => it.cid)
    const uids = cids.map(uidFor)
    invalidateFetches()
    setTasks((ts) => [...ts, ...items.map((it, i) => draftTask(uids[i], it.listId, it.body))])
    const failed: number[] = []
    for (let i = 0; i < items.length; i++) {
      try {
        const t = await api.createTask(items[i].listId, { ...items[i].body, client_id: cids[i] })
        settleCreate(uids[i], key, t)
      } catch (e) {
        if (e instanceof AuthError) {
          // Session died mid-batch. Drop every stand-in that can no longer land
          // and hand the rest back as failures, so nothing is left painted.
          const rest = uids.slice(i)
          setTasks((ts) => ts.filter((x) => !rest.includes(x.uid)))
          onExpire()
          return [...failed, ...items.map((_, n) => n).filter((n) => n >= i)]
        }
        console.error(e)
        failed.push(i)
        setTasks((ts) => ts.filter((x) => x.uid !== uids[i]))
      }
      onProgress(i + 1)
    }
    return failed
  }

  const addSub = (parent: string, summary: string) => {
    const p = tasks.find((x) => x.uid === parent)   // a subtask lives in its parent's list
    if (p) void create(p.list, { summary, parent }, pending.current.get(parent))
  }

  const toggle = async (t: Task) => {
    const done = !t.completed
    invalidateFetches()
    patchLocal(t.uid, {
      completed: done, cancelled: false, status: done ? 'COMPLETED' : 'NEEDS-ACTION',
    })
    settle(await guard(() => api.complete(t.list, t.uid, done)), t)
  }

  const remove = async (t: Task) => {
    const at = tasks.findIndex((x) => x.uid === t.uid)  // where to restore it on failure
    const key = loadKey
    invalidateFetches()
    setTasks((ts) => ts.filter((x) => x.uid !== t.uid))
    if ((await guard(() => api.deleteTask(t.list, t.uid))) === undefined && key === keyRef.current) {
      setTasks((ts) => {
        if (ts.some((x) => x.uid === t.uid)) return ts
        const next = ts.slice()
        next.splice(at < 0 ? next.length : Math.min(at, next.length), 0, t)
        return next
      })
    }
  }

  const saveDetail = async (t: Task, patch: Record<string, unknown>) => {
    const opt: Partial<Task> = {}
    if ('summary' in patch) opt.summary = patch.summary as string
    if ('notes' in patch) opt.notes = (patch.notes as string) ?? null
    if ('tags' in patch) opt.tags = patch.tags as string[]
    if ('priority' in patch) opt.priority_label = (patch.priority as string) || 'none'
    if ('due' in patch) {
      opt.due = (patch.due as string) ?? null
      opt.due_is_date = typeof patch.due === 'string' && !patch.due.includes('T')
    }
    if ('start' in patch) opt.start = (patch.start as string) ?? null
    if ('status' in patch) {
      opt.status = patch.status as string
      opt.completed = patch.status === 'COMPLETED'
      opt.cancelled = patch.status === 'CANCELLED'
    }
    invalidateFetches()
    patchLocal(t.uid, opt)
    settle(await guard(() => api.patchTask(t.list, t.uid, patch)), t)
  }

  // Repair, once per row, the subtasks written before `uidFor` existed: their
  // RELATED-TO holds the create's client_id rather than the uid derived from
  // it, so it resolves to nothing. Reinterpreting them at render (TasksView)
  // makes them nest again here, but the stored pointer is what the server
  // counts and what every other CalDAV client on these collections reads —
  // Tasks.org and jtx Board show the same orphan until this lands.
  //
  // The signature is exact: bare client_id shape, naming no task, while
  // `${value}@tasksd` names one in the same list. A RELATED-TO another client
  // authored cannot match it without that sibling existing, so this never
  // rewrites someone else's data. Attempts are remembered whether or not they
  // succeed, so a row the server refuses is not retried in a loop.
  const repaired = useRef(new Set<string>())
  useEffect(() => {
    if (!loaded) return          // cached rows are not proof a parent is missing
    const byUid = new Map(tasks.map((t) => [t.uid, t] as const))
    for (const t of tasks) {
      const p = t.parent
      if (!p || byUid.has(p) || repaired.current.has(t.uid)) continue
      if (!LEGACY_PARENT.test(p)) continue
      const real = byUid.get(uidFor(p))
      if (!real || real.list !== t.list) continue
      repaired.current.add(t.uid)
      console.info(`repairing subtask ${t.uid}: parent ${p} → ${real.uid}`)
      // Painted locally too, so the row settles on the repaired parent rather
      // than waiting for the write's own SSE bump to come back around.
      patchLocal(t.uid, { parent: real.uid })
      void guard(() => api.patchTask(t.list, t.uid, { parent: real.uid }))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks, loaded])

  const ordered = useMemo(() => orderLists(lists, taskGroups), [lists, taskGroups])

  const value: TaskData = {
    lists: ordered, serverOrderedLists: lists, tasks, listsLoaded, loaded, setLists,
    create, createMany, addSub, toggle, remove, saveDetail,
  }
  return <TaskCtx.Provider value={value}>{children}</TaskCtx.Provider>
}

// ── calendars ───────────────────────────────────────────────────────────────

function CalendarProvider({ rev, guard, enabled, children }: {
  rev: number; guard: Guard; enabled: boolean; children: ReactNode
}) {
  const [cals, setCals] = useState<List[]>(() => readCachedCalendars() ?? [])
  const [loaded, setLoaded] = useState(false)
  // Windows fetched this session, so paging back to a month already seen is
  // free. Only the newest is mirrored to disk — it is the one the app boots on,
  // and the only place an instant paint is the difference between a grid of
  // events and a blank one.
  const [windows, setWindows] = useState<Map<string, CalEvent[]>>(new Map())
  const seeded = useRef<{ key: string; rows: CalEvent[] } | null>(null)
  const latest = useRef<string>('')

  useEffect(() => {
    if (!enabled) return
    guard(async () => {
      const cs = await api.calendars()
      if (Array.isArray(cs)) setCals(cs)
    }).finally(() => setLoaded(true))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rev, enabled])

  useEffect(() => {
    if (!loaded) return
    const t = setTimeout(() => cacheCalendars(cals), CACHE_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [cals, loaded])

  useEffect(() => {
    const key = latest.current
    if (!key) return
    const [from, to] = key.split('|')
    const rows = windows.get(key)
    if (!rows) return
    const t = setTimeout(() => cacheEvents(from, to, rows), CACHE_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [windows])

  // Every load is stamped, and only the newest for its window is allowed to
  // land. A fetch fans out one request per calendar and awaits them all, so two
  // clicks on › put two batches in flight and whichever settles last used to
  // win. When the older batch settled second the grid held the previous month's
  // events — and since `bucketByDay` clips to the visible six weeks, almost none
  // of them matched a rendered day, so the month came up *empty*.
  const gen = useRef(0)
  const inflight = useRef(new Set<string>())

  const fetchWindow = useCallback((from: string, to: string, forCals: List[]) => {
    const key = windowKey(from, to)
    const mine = ++gen.current
    inflight.current.add(key)
    void guard(async () => {
      const per = await Promise.all(forCals.map((c) => api.events(c.id, from, to)))
      const rows = per.filter(Array.isArray).flat()
      if (gen.current !== mine) return
      setWindows((w) => new Map(w).set(key, rows))
    }).finally(() => inflight.current.delete(key))
  }, [guard])

  // What a window has been asked for, so re-renders do not re-request it. The
  // calendar set and `rev` are part of the identity: archiving a calendar or a
  // server-side change has to refetch, a scroll does not.
  const asked = useRef(new Map<string, string>())

  const requestWindow = useCallback((from: string, to: string, forCals: List[]) => {
    const key = windowKey(from, to)
    latest.current = key
    if (!enabled || !forCals.length) return
    const stamp = `${rev}|${forCals.map((c) => c.id).join(',')}`
    if (asked.current.get(key) === stamp) return
    asked.current.set(key, stamp)
    fetchWindow(from, to, forCals)
  }, [rev, enabled, fetchWindow])

  const reload = useCallback((from: string, to: string, forCals: List[]) => {
    asked.current.delete(windowKey(from, to))
    if (forCals.length) fetchWindow(from, to, forCals)
  }, [fetchWindow])

  const eventsFor = useCallback((from: string, to: string): CalEvent[] => {
    const key = windowKey(from, to)
    const rows = windows.get(key)
    if (rows) return rows
    // Fall back to the disk mirror, read once per window so a miss is not
    // re-parsed on every render.
    if (seeded.current?.key !== key) seeded.current = { key, rows: readCachedEvents(from, to) ?? [] }
    return seeded.current.rows
  }, [windows])

  const setEvents = useCallback((from: string, to: string,
    next: (prev: CalEvent[]) => CalEvent[]) => {
    const key = windowKey(from, to)
    setWindows((w) => {
      const prev = w.get(key) ?? (seeded.current?.key === key ? seeded.current.rows : [])
      return new Map(w).set(key, next(prev))
    })
  }, [])

  const value: CalendarData = {
    cals, loaded, setCals, eventsFor, requestWindow, setEvents, reload,
  }
  return <CalendarCtx.Provider value={value}>{children}</CalendarCtx.Provider>
}
