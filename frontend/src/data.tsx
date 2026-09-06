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
import { sortTasks, taskKey } from './order'
import {
  CACHE_DEBOUNCE_MS,
  cacheCalendars, cacheEvents, cacheLists, cacheTasks,
  readCachedCalendars, readCachedEvents, readCachedLists, readCachedTasks,
} from './cache'
import { makeGuard } from './util'

/** The shape a bare client_id has, matching the backend's `_CLIENT_ID_RE`. */
const LEGACY_PARENT = /^[0-9a-f]{16,64}$/

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
  /** The lists came from the server, not from the disk cache. Gate destructive
   *  pruning on this, never on `listsLoaded`. */
  listsOk: boolean
  /** …and the tasks behind them have landed too. Kept separate because the
   *  lists arrive a hop earlier, and "nothing to do here" said in that gap is
   *  just as wrong as saying the account has no lists. */
  loaded: boolean
  setLists: (next: List[]) => void
  /** `cid` is the create's idempotency key, minted here when not supplied. Pass
   *  one to make a RETRY of the same logical create idempotent: the backend
   *  derives the VTODO's uid from it, so a replay is answered by the resource
   *  already written instead of authoring a second task. `createMany` has taken
   *  an explicit cid per item all along, for the same reason. */
  create: (listId: string, body: CreateTaskBody,
    after?: Promise<Task | undefined>, cid?: string) => Promise<Task | undefined>
  createMany: (items: Array<{ listId: string; body: CreateTaskBody; cid: string }>,
    onProgress: (done: number) => void) => Promise<number[]>
  addSub: (parent: string, summary: string) => void
  toggle: (t: Task) => Promise<void>
  remove: (t: Task) => Promise<void>
  saveDetail: (t: Task, patch: Record<string, unknown>) => Promise<void>
  /** "Notify me N minutes before this is due", or -1 to clear it. Its own call
   *  rather than a field on saveDetail: the reminder is app-only, and sending
   *  it through PATCH would PUT the VTODO back and move its etag, making every
   *  other CalDAV client re-fetch a resource that did not change. */
  setReminder: (t: Task, minutes: number) => Promise<void>
  /** Set the task aside without finishing or abandoning it, or bring it back.
   *  Its own call for the same reason `setReminder` is: parked is app-only, and
   *  routing it through PATCH would PUT the VTODO back and move its etag, so
   *  every other CalDAV client would re-fetch a resource that did not change. */
  park: (t: Task, parked: boolean) => Promise<void>
  /** Move the task `from` to where `target` currently sits WITHIN `run`. Same
   *  gesture as the sidebar's list drag: dropping on a row below lands after
   *  it, above lands before it. Positions are assigned across every task on the
   *  account, not just the visible ones — see `reorder` below.
   *
   *  `run` is the sequence the two rows are DISPLAYED in: the pane's top-level
   *  rows, or one parent's subtasks. It is a parameter rather than re-derived
   *  here because those are different sequences and only the caller knows which
   *  one the gesture happened in — a subtask dragged among its siblings must
   *  land where the sibling list says, not where the account-wide sequence
   *  happens to put it.
   *
   *  Takes the ROWS, not their uids. A uid is unique within a collection but not
   *  across the account, and the local array is every list merged — so a VTODO
   *  copied between lists (which Tasks.org, DAVx5 and Thunderbird all do,
   *  preserving the UID) gave `findIndex` two candidates and it moved whichever
   *  sorted first. `taskKey` is the identity everywhere else in this file. */
  reorder: (run: Task[], from: Task, target: Task) => Promise<void>
  /** The NAMES of the lists whose last fetch failed, empty when all answered.
   *  The `windowErrors` analogue on the task side, and for the same reason its
   *  comment gives: a pane that is short and does not say so is a confident lie
   *  about the account. */
  taskListErrors: string[]
  /** The same lists by ID — the key a day-plan row joins on. A task row from
   *  one of these is UNKNOWN, not gone: the server still names and credits the
   *  task, this client just could not read the list it is in. `focus.ts` and
   *  the Home plan module read this so such a row is never counted finished or
   *  called orphan off the absence of a task that was never fetched. */
  taskListsFailed: string[]
  /** Re-run the task fan-out. The effect keys on `loadKey`/`rev`, and `rev`
   *  only moves when the SERVER publishes a change — so on an idle account a
   *  failed fetch had no way back short of reloading the page. */
  reloadTasks: () => void
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
  /** Calendars whose fetch for this window failed, by name.
   *
   *  The fan-out keeps whatever loaded rather than discarding the month, which
   *  means the grid can be SHORT — so what is missing has to be sayable, or the
   *  user reads a partial month as a complete one. Empty when everything
   *  landed. */
  windowErrors: (from: string, to: string) => string[]
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
  // Distinct from `listsLoaded`, which only means "the attempt finished" — the
  // spinner and the task fetch both want that. This means the server actually
  // answered with a list, and it is what gates anything DESTRUCTIVE: pruning
  // list-scoped settings against a failed fetch prunes them against the stale
  // disk cache, and writes the result back, so one transient 500 at startup
  // permanently loses the user's grouping.
  const [listsOk, setListsOk] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!enabled) return
    guard(async () => {
      const ls = await api.lists()
      // A malformed body must not become the state every render maps over —
      // `guard` only shields us from a rejection, not from a 200 with junk in it.
      if (Array.isArray(ls)) {
        setLists(ls)
        setListsOk(true)
      }
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
  // Sorted: the identity is the list SET. A sidebar drag-reorder hands back the
  // same ids in a new order, and an order-sensitive key made that a full
  // refetch of every task in the account for data that cannot have changed —
  // while ALSO failing the commit guard below, so any response already in
  // flight was thrown away. Nothing downstream wants the order: the fan-out is
  // a `Promise.all`, the result is flattened, and rows are ordered at render by
  // `sortTasks`. Both consumers read this one constant, which is why it is
  // fixed here rather than in the effect's dependency list — sorting only the
  // dep would stop the refetch while leaving the guard order-sensitive, and
  // then an in-flight response would be discarded with nothing to re-issue it.
  const loadKey = `*|${lists.map((l) => l.id).slice().sort().join(',')}`
  const keyRef = useRef(loadKey)
  keyRef.current = loadKey
  const fetchToken = useRef(0)
  const invalidateFetches = () => { fetchToken.current += 1 }
  const [listErrors, setListErrors] = useState<List[]>([])
  // Memoised: both arrays sit in a context value that is rebuilt every render,
  // and consumers put them in effect dependency lists.
  const listErrorNames = useMemo(() => listErrors.map((l) => l.name), [listErrors])
  const listErrorIds = useMemo(() => listErrors.map((l) => l.id), [listErrors])
  // The retry's own signal. `rev` cannot serve: it moves only when the server
  // publishes a change, so on an idle account a failed fan-out had nothing to
  // re-issue it.
  const [taskNonce, setTaskNonce] = useState(0)
  const reloadTasks = useCallback(() => setTaskNonce((n) => n + 1), [])

  // The three facts that decide whether a discarded fan-out has to be
  // re-issued by hand. A fan-out is dropped whenever a write invalidates it;
  // if that write LANDS, the server publishes and the SSE `rev` bump refetches,
  // so nothing is owed. If it FAILS, nothing is published and nothing else will
  // ask again. Re-issued only once every write is settled, so a burst of
  // writes is one refetch and a fan-out is never re-issued into the flight of
  // a write that would only drop it again. The commit path clears all three.
  const droppedFetch = useRef(false)
  const failedWrite = useRef(false)
  const writesInFlight = useRef(0)
  const reissueIfOrphaned = () => {
    if (!droppedFetch.current || !failedWrite.current || writesInFlight.current > 0) return
    droppedFetch.current = false
    failedWrite.current = false
    reloadTasks()
  }
  /** `guard`, counted. Every optimistic write below goes through this so the
   *  bookkeeping above cannot be forgotten by one of them. */
  const write = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    writesInFlight.current += 1
    const out = await guard(fn)
    writesInFlight.current -= 1
    if (out === undefined) failedWrite.current = true
    reissueIfOrphaned()
    return out
  }

  // Waits for the real lists rather than fanning out over the cached ones: a
  // seeded id may name a list deleted in another client, and a 404 per stale
  // list would raise a toast apiece. The cache is already painting meanwhile,
  // so the extra hop costs nothing on screen.
  useEffect(() => {
    if (!enabled || !listsLoaded) return
    if (lists.length === 0) {
      setTasks([])
      setListErrors([])
      setLoaded(true)
      return
    }
    const token = ++fetchToken.current
    const key = loadKey
    guard(async () => {
      // `allSettled`, not `all`, exactly as the calendar window below does and
      // for the same reason its comment gives. One list answering 500 — one
      // poison VTODO from jtx Board or Tasks.org that 500s the DTO builder for
      // its collection, a documented failure class here — rejected the whole
      // batch, so `setTasks` never ran, `loaded` flipped true anyway, and EVERY
      // task surface in the app (TasksView, HomeView, TodayView, the calendar's
      // task overlay) reads that one array. TasksView then rendered "Nothing to
      // do here.": the owner was told their account was empty.
      const per = await Promise.allSettled(lists.map((l) => api.tasks(l.id)))
      const ts = per.flatMap((r) =>
        r.status === 'fulfilled' && Array.isArray(r.value) ? r.value : [])
      const failed = lists
        .filter((l, i) => per[i].status === 'rejected'
          || !Array.isArray((per[i] as PromiseFulfilledResult<Task[]>).value))
      // An AuthError anywhere is the SESSION, not one list: let it out to
      // `guard` so the app routes to the login card rather than reporting the
      // whole account as a set of broken lists.
      const auth = per.find((r) => r.status === 'rejected'
        && (r as PromiseRejectedResult).reason instanceof AuthError)
      if (auth) throw (auth as PromiseRejectedResult).reason
      if (token !== fetchToken.current || key !== keyRef.current) {
        // Superseded by a write. The write's own SSE `rev` bump re-issues this
        // once the server has published the change — but a write that FAILS
        // publishes nothing, and this was the only fan-out for this `rev`. So
        // the drop is remembered, and re-issued the moment it is known that no
        // replacement is coming (see `reissueIfOrphaned`). Without that, the
        // pre-fetch array — on a cold boot the disk mirror, up to 14 days old —
        // stayed painted as the live account with `loaded` true, no error and
        // no retry, on an idle account indefinitely.
        droppedFetch.current = true
        reissueIfOrphaned()
        return
      }
      droppedFetch.current = false
      failedWrite.current = false
      // Only when SOMETHING landed, the lesson the calendar path already
      // carries: writing `[]` for a fan-out where every list failed replaces
      // rows that are still on screen with a blank pane, which is a worse blank
      // than the one this fixes. A total failure leaves the previous rows up
      // and says so through `taskListErrors`.
      if (failed.length < lists.length) setTasks(ts)
      setListErrors(failed)
    }).finally(() => setLoaded(true))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadKey, rev, enabled, listsLoaded, taskNonce])

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
  //
  // Keyed by (list, uid), like `sortTasks` and the reorder snapshot below: the
  // backend keys items on (collection_href, uid), so a uid copied into a second
  // list is two distinct tasks. Matching on the bare uid made them one as far as
  // every optimistic write was concerned — ticking one row's box marked both
  // done on screen, and deleting one removed both, each disagreeing with the
  // server until a full refetch. `patchLocal` takes the whole task rather than a
  // uid so the list travels with it.
  const patchLocal = (target: Task, patch: Partial<Task>) =>
    setTasks((ts) => ts.map((t) => (taskKey(t) === taskKey(target) ? { ...t, ...patch } : t)))
  const settle = (dto: Task | undefined, orig: Task) =>
    setTasks((ts) => ts.map((t) => (taskKey(t) === taskKey(orig) ? (dto ?? orig) : t)))

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
    completed: false, cancelled: false, parked: false, parked_at: null,
    // `priority` is the numeric iCal field the server derives; the rows render
    // `priority_label`, so the stand-in paints the right stripe right away and
    // the server's DTO fills the number in when it lands.
    priority: null, priority_label: body.priority || 'none',
    percent_complete: null, due: body.due ?? null,
    due_is_date: !!body.due && !body.due.includes('T'),
    start: body.start ?? null, start_is_date: !!body.start && !body.start.includes('T'),
    tags: body.tags ?? [], parent: body.parent ?? null, children: [],
    child_count: 0, completed_child_count: 0, derived_percent: null,
    // No manual position: a new task sorts by its due date like anything else
    // the user hasn't placed by hand (see order.ts). The list is sorted at
    // render, so this stand-in paints where the real task will be — it does not
    // matter that `create` appends it to the end of the array.
    pinned: false, sort_order: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null,
    // Nothing here is a stand-in for a server value the way `priority_label` is
    // above — these are facts about a task that does not exist on the wire yet.
    // It has no COMPLETED stamp (it is not done), no RRULE (this app authors
    // none — VTODO recurrence is gated), and no CREATED/LAST-MODIFIED until the
    // server writes the VTODO and the settled DTO replaces this row.
    completed_at: null, has_rrule: false, created: null, last_modified: null,
    href: '', etag: '',
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
    after?: Promise<Task | undefined>, explicitCid?: string): Promise<Task | undefined> => {
    if (!listId) return undefined
    const cid = explicitCid ?? clientId()
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
      const t = await write(() => api.createTask(listId, { ...body, client_id: cid }))
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
  // What the create ASKED for, against what came back.
  //
  // A create is idempotent on its client_id: the second POST under a slug is
  // answered by confirming the resource already written under it, body ignored
  // (`_put_new` swallows the 412 when the occupant carries the same UID, and
  // `create_task` returns the stored resource). That is exactly right for the
  // failure the composer's retry exists for — the write landed and the reply was
  // lost — and it is why a kept row must NOT mint a fresh id: doing so would
  // author a duplicate.
  //
  // But a row keeps its id across a retry while every field except its title can
  // be edited in between, and the whole shared strip is re-read on each submit.
  // So the user could correct the due date, press Add, and have the correction
  // silently dropped: the server confirmed the old resource, `settleCreate`
  // painted the old DTO, nothing was reported as failed, and the modal closed on
  // a success it did not get.
  //
  // No server signal is needed to notice. If the resource that came back does
  // not carry what this call asked for, this was a replay of an earlier body,
  // and the difference is exactly the correction the user made — so send it as
  // the PATCH it should have been. Only fields the caller explicitly SET are
  // compared, so a server-side normalisation of something we left alone cannot
  // provoke a write.
  // Both sides normalised before comparing, because two of these fields do not
  // have the same SHAPE on the way out as on the way in:
  //
  //   body.due       'YYYY-MM-DDTHH:MM'      Task.due        _iso() -> with seconds
  //   body.start     'YYYY-MM-DDTHH:MM'      Task.start      _iso() -> with seconds
  //   body.priority  'high'                  Task.priority   the iCal integer 1
  //
  // THREE rows, not the two this comment first listed. `start` was missed
  // because `bodyFrom` only emits a time on it for a timed row, so the corpus
  // the widened double drove never carried one — the same blind spot, one field
  // over. `sameDue` is named for `due` and used for both; the rule is identical.
  //
  // Compared raw, every bulk row carrying a timed due or a priority looked like
  // a replay of a different body and provoked a PATCH — a 20-row add became 40
  // writes, each a CalDAV PUT with a SEQUENCE bump every other client sees. The
  // comment below claims "a server-side normalisation of something we left alone
  // cannot provoke a write"; normalisation of the fields we DID set is exactly
  // what provoked it. `priority_label` is the DTO's own label form and is what
  // the body should have been compared against all along.
  const sameDue = (sent: string | undefined, got: string | null): boolean => {
    const a = sent ?? null
    const b = got ?? null
    if (a === b) return true
    if (a === null || b === null) return false
    // A timed value differs only by the seconds the server appends.
    return a.includes('T') && b.startsWith(a) && /^:\d{2}$/.test(b.slice(a.length))
  }

  const reconcileReplay = async (
    listId: string, body: CreateTaskBody, got: Task,
  ): Promise<Task> => {
    const patch: Record<string, unknown> = {}
    if ('summary' in body && body.summary !== got.summary) patch.summary = body.summary
    if ('due' in body && !sameDue(body.due, got.due)) patch.due = body.due ?? null
    if ('start' in body && !sameDue(body.start, got.start)) {
      patch.start = body.start ?? null
    }
    if ('notes' in body && (body.notes ?? null) !== (got.notes ?? null)) {
      patch.notes = body.notes ?? null
    }
    if ('priority' in body
        && (body.priority ?? 'none') !== (got.priority_label ?? 'none')) {
      patch.priority = body.priority
    }
    if ('tags' in body
        && (body.tags ?? []).join('\u0000') !== (got.tags ?? []).join('\u0000')) {
      patch.tags = body.tags
    }
    if (!Object.keys(patch).length) return got
    return await api.patchTask(listId, got.uid, patch)
  }

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
    // The whole batch is ONE write as far as the dropped-fan-out bookkeeping
    // goes: it bypasses `guard` (nine toasts for nine rows), so it settles the
    // same three facts by hand in `finally` — see `write`.
    writesInFlight.current += 1
    try {
      for (let i = 0; i < items.length; i++) {
        try {
          const created = await api.createTask(
            items[i].listId, { ...items[i].body, client_id: cids[i] })
          settleCreate(uids[i], key, created)
          // AWAITED, but its failure is not this row's failure.
          //
          // The create has landed and been painted; a transient failure on the
          // follow-up correction must not mark the row failed, which would keep it
          // in the composer and have the user add it a second time. That is what
          // the inner catch is for.
          //
          // It must NOT be detached, though: `createMany` resolving is what closes
          // AddMultipleModal, so a correction still in flight lands on a task the
          // user can already see and act on — ticking its box, or deleting it —
          // and `settleCreate` then writes the server's older DTO back over them.
          // Awaiting keeps the whole batch inside the modal, which is where it was
          // before this was moved.
          try {
            const fixed = await reconcileReplay(items[i].listId, items[i].body, created)
            if (fixed !== created) settleCreate(uids[i], key, fixed)
          } catch (e) {
            console.error(e)
          }
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
    } finally {
      writesInFlight.current -= 1
      if (failed.length) failedWrite.current = true
      reissueIfOrphaned()
    }
  }

  const addSub = (parent: string, summary: string) => {
    // A subtask lives in its parent's list. With one uid in two lists this can
    // still pick the wrong copy — the caller passes a bare uid — but both
    // candidates carry the same parent uid, so the subtask lands under a real
    // parent either way. Retyping TaskGroup's whole uid-shaped prop surface is
    // a separate finding; see docs/AUDIT.md.
    const p = tasks.find((x) => x.uid === parent)
    if (p) void create(p.list, { summary, parent }, pending.current.get(parent))
  }

  const toggle = async (t: Task) => {
    const done = !t.completed
    invalidateFetches()
    patchLocal(t, {
      completed: done, cancelled: false, status: done ? 'COMPLETED' : 'NEEDS-ACTION',
    })
    settle(await write(() => api.complete(t.list, t.uid, done)), t)
  }

  const remove = async (t: Task) => {
    const gone = taskKey(t)                            // (list, uid): see patchLocal
    const at = tasks.findIndex((x) => taskKey(x) === gone)  // where to restore it on failure
    const key = loadKey
    invalidateFetches()
    setTasks((ts) => ts.filter((x) => taskKey(x) !== gone))
    if ((await write(() => api.deleteTask(t.list, t.uid))) === undefined && key === keyRef.current) {
      setTasks((ts) => {
        if (ts.some((x) => taskKey(x) === gone)) return ts
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
    patchLocal(t, opt)
    settle(await write(() => api.patchTask(t.list, t.uid, patch)), t)
  }

  const park = async (t: Task, parked: boolean) => {
    // Painted immediately and reconciled, like every write here. `parked_at` is
    // painted as a placeholder rather than guessed at: the row disappears from
    // the view on this tick anyway, and the server's stamp replaces it on
    // settle. Only the flag decides anything.
    patchLocal(t, { parked, parked_at: parked ? new Date().toISOString() : null })
    invalidateFetches()
    settle(await write(() => api.park(t.list, t.uid, parked)), t)
  }

  const setReminder = async (t: Task, minutes: number) => {
    // Painted immediately like every other write here, then reconciled. -1 is
    // the clear sentinel on the wire and `null` is what the DTO carries for it.
    patchLocal(t, { notify_minutes_before: minutes < 0 ? null : minutes })
    invalidateFetches()
    settle(await write(() => api.setTaskReminder(t.list, t.uid, minutes)), t)
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
      patchLocal(t, { parent: real.uid })
      void guard(() => api.patchTask(t.list, t.uid, { parent: real.uid }))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks, loaded])

  // Move one task and renumber everything. The whole sequence goes to the
  // server because manual position has to be comparable across lists — the
  // pane is always the merged view — and because sending only the visible rows
  // would leave a hidden list's positions stranded among the new ones.
  //
  // Every task on the account is already in `tasks` (the fetch fans out over
  // every list unconditionally), so "the whole sequence" costs nothing to
  // build: sort by the comparator that is already deciding what is on screen,
  // splice the dragged row in, and hand that over.
  // Keyed on `taskKey`, not on the bare uid — including the no-op check. The
  // backend keys items on (collection_href, uid), so a uid copied into a second
  // list is two distinct tasks, and this array is every list merged. Matching on
  // the uid gave `findIndex` two candidates and moved whichever sorted first, so
  // dragging the Work copy moved the Home copy; `reorder` then renumbers
  // `sort_order` for EVERY task on the account and POSTs it, making that
  // permanent. And `uid === target` was true for a drop of one copy onto the
  // other, so that gesture silently did nothing at all — the same cause, and the
  // reason the early return had to move to keys with the rest.
  const reorder = async (run: Task[], from_: Task, target_: Task) => {
    if (taskKey(from_) === taskKey(target_)) return
    // Spliced in the RUN — the sequence on screen — not in the account-wide one.
    // Those two agree while every row is placed, or while none is; they part
    // company for a row created since the last drag, because `sortTasks` puts an
    // unplaced row "half a step before its first later neighbour" and that
    // neighbour is a different task in a subset than in the whole account. The
    // gesture is about what the user can see, so it is measured there: a subtask
    // dragged past the sibling above it lands above that sibling, whatever the
    // account-wide sequence thinks of the pair.
    const order = run.slice()
    const from = order.findIndex((t) => taskKey(t) === taskKey(from_))
    // Read before the removal, like Sidebar's list drag: dropping on a row
    // further down lands after it, further up lands before it, which is what
    // the gesture looks like it is doing.
    const to = order.findIndex((t) => taskKey(t) === taskKey(target_))
    if (from < 0 || to < 0) return
    const [moved] = order.splice(from, 1)
    order.splice(to, 0, moved)

    // Folded back into the account-wide sequence, which is what gets written:
    // manual position has to be comparable across lists (the pane is always the
    // merged view) and sending only the run would leave every other row's
    // position stranded among the new ones.
    //
    // The run's members keep the SLOTS they already occupy and are re-dealt into
    // them in the order the drop produced. Nothing outside the run moves, and
    // the run's own order afterwards is exactly the one the user just saw — the
    // property that makes the drop indicator and the result the same statement.
    // The count is exact: `run` is built from `tasks` and `taskKey` is unique
    // within it, so there is one slot per member.
    const inRun = new Set(run.map(taskKey))
    let dealt = 0
    const placed = sortTasks(tasks).map(
      (t) => (inRun.has(taskKey(t)) ? order[dealt++] : t))

    // Paint the new positions locally so the row stays where it was dropped:
    // the comparator reads sort_order first, so writing 1..N here is the same
    // arithmetic the server is about to do.
    const next = placed.map((t, i) => ({ ...t, sort_order: i + 1 }))
    invalidateFetches()
    // Only the positions are remembered, not the whole array. Snapshotting
    // `tasks` and restoring it wholesale also reverted anything that landed
    // while the reorder was in flight — an SSE update, a completed task, an edit
    // from another tab — silently undoing a write the user had just made.
    // Keyed by (list, uid), like sortTasks: a uid copied into a second list is
    // two distinct tasks, and collapsing them onto one key restored the wrong
    // one's position on a failed reorder.
    const before = new Map(tasks.map((t) => [taskKey(t), t.sort_order ?? null]))
    setTasks(next)
    const ok = await write(() =>
      api.reorderTasks(placed.map((t) => ({ list: t.list, uid: t.uid }))))
    // The guard has already raised the toast; put the old positions back rather
    // than leaving the UI claiming a move that never landed.
    if (ok === undefined) {
      setTasks((cur) => cur.map((t) => (
        before.has(taskKey(t)) ? { ...t, sort_order: before.get(taskKey(t))! } : t)))
    }
  }

  const ordered = useMemo(() => orderLists(lists, taskGroups), [lists, taskGroups])

  const value: TaskData = {
    lists: ordered, serverOrderedLists: lists, tasks, listsLoaded, listsOk, loaded, setLists,
    create, createMany, addSub, toggle, remove, saveDetail, setReminder, park, reorder,
    taskListErrors: listErrorNames, taskListsFailed: listErrorIds, reloadTasks,
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
  const [windowFails, setWindowFails] = useState<Map<string, string[]>>(new Map())
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
  // Per WINDOW, not one counter for all of them. A single generation meant any
  // newer fetch superseded any older one, so paging January -> February dropped
  // January's response when it landed second — while `asked` had already
  // recorded January as fetched, so coming back to it never re-requested and the
  // grid stayed empty until something unrelated bumped `rev`. A fetch should
  // only ever be superseded by a newer fetch for the SAME window.
  const gen = useRef(new Map<string, number>())

  // What a window has been asked for, so re-renders do not re-request it. The
  // calendar set and `rev` are part of the identity: archiving a calendar or a
  // server-side change has to refetch, a scroll does not.
  //
  // Declared above `fetchWindow` because the failure path has to reach it.
  const asked = useRef(new Map<string, string>())

  const fetchWindow = useCallback((from: string, to: string, forCals: List[]) => {
    const key = windowKey(from, to)
    const mine = (gen.current.get(key) ?? 0) + 1
    gen.current.set(key, mine)
    void guard(async () => {
      // `allSettled`, not `all`. One calendar answering 502 used to reject the
      // whole window, so every OTHER calendar's events were discarded with it
      // and the user got a blank month. Finding 41 fixed the part that made
      // that permanent — the window is no longer recorded as fetched on failure
      // — but the re-request had the same shape, so while one collection was
      // unhealthy the month stayed empty.
      //
      // Keeping what arrived is only half of it: a month that is short and does
      // not say so is a confident lie, and this grid sits beside a booking page
      // whose whole job is not to under-report. So the failures are recorded by
      // name and rendered, and a partial window is never silently partial.
      const per = await Promise.allSettled(forCals.map((c) => api.events(c.id, from, to)))
      const rows = per.flatMap((r) =>
        r.status === 'fulfilled' && Array.isArray(r.value) ? r.value : [])
      const failed = forCals
        .filter((c, i) => per[i].status === 'rejected'
          || !Array.isArray((per[i] as PromiseFulfilledResult<CalEvent[]>).value))
        .map((c) => c.name)
      // An AuthError anywhere is the session, not one collection: let it out to
      // `guard` so the app routes to the login card rather than reporting the
      // owner's whole account as a set of broken calendars.
      const auth = per.find((r) => r.status === 'rejected'
        && (r as PromiseRejectedResult).reason instanceof AuthError)
      if (auth) throw (auth as PromiseRejectedResult).reason
      if (gen.current.get(key) === mine) {
        // Only when SOMETHING landed. `[]` is truthy, and `eventsFor` tests
        // presence rather than length (`if (rows) return rows`), so writing an
        // empty array for a window where every calendar failed shadowed the
        // disk mirror — the month painted blank where `Promise.all` used to
        // reject, leave no entry, and fall through to the cache. That is a
        // worse blank than the one this finding is about, because the rows to
        // draw were sitting on disk.
        if (failed.length < forCals.length) setWindows((w) => new Map(w).set(key, rows))
        setWindowFails((m) => {
          const next = new Map(m)
          if (failed.length) next.set(key, failed)
          else next.delete(key)
          return next
        })
      }
      // Only a WHOLE-window failure leaves the window un-asked, so a healthy
      // calendar's month is not re-requested on every page-turn because a
      // broken one is still broken.
      return failed.length < forCals.length ? true : undefined
    }).then((ok) => {
      // `requestWindow` records the window BEFORE the fetch, so a failure left
      // it recorded as fetched with nothing in `windows` — and the fan-out is a
      // `Promise.all`, so one 502 through the tunnel blanks the whole month.
      // Paging away and back never re-requested it; only an SSE bump, archiving
      // a calendar or an edit ever recovered it, because those change the stamp.
      //
      // `undefined` is what `makeGuard` returns from its catch and the only way
      // to get it: the superseded branch above returns `true` too, deliberately,
      // so a stale-but-successful response does not un-ask a window that a newer
      // fetch is already handling. Clearing on every settle would re-request on
      // every fast page-turn.
      if (ok === undefined) asked.current.delete(key)
    })
  }, [guard])

  // Everything this provider holds, dropped when the session goes away.
  //
  // `onLogout` deliberately clears the DISK mirror (App.tsx calls `clearCache()`
  // and `setCacheUser('')`, and cache.ts is user- and version-keyed for exactly
  // that reason) — but `DataProvider` sits ABOVE the auth branch on purpose, so
  // it never unmounts and nothing reset this state. On the next login
  // `CalendarView` remounted, `eventsFor` hit `windows` and painted the previous
  // session's rows, and `requestWindow` short-circuited because `asked` still
  // held the same stamp, so the month was never refetched at all.
  //
  // In the multi-account reading of the trust model that serves one account's
  // events to another; in the single-account one it means "log out at night, log
  // back in in the morning" shows a frozen snapshot missing everything DAVx5 or
  // Apple wrote overnight. `TaskProvider` already refetches — its effects list
  // `enabled` as a dep — which made this an inconsistency rather than a design.
  //
  // On the TRUE->FALSE TRANSITION only, which is the whole of what "the session
  // went away" means. `enabled` is `auth === 'in'` and `auth` starts at
  // `'loading'`, so this effect also ran ON MOUNT — before `/api/me` had
  // answered — and threw away the `readCachedCalendars()` seed two lines of
  // constructor above it, along with `seeded.current` and `latest.current`. The
  // calendar half of `cache.ts` was therefore dead in practice: written on every
  // change, read once, and cleared before the first paint that could use it. A
  // cold boot on a slow connection showed an empty calendar for the whole
  // round trip, which is exactly what the mirror exists to prevent.
  //
  // `wasEnabled` holds the value this effect last saw. The guard is the STEP,
  // not the level, so no first invocation can be a fall whatever the ref is
  // seeded with — seeding it with `enabled` says what it means rather than
  // relying on that.
  const wasEnabled = useRef(enabled)
  useEffect(() => {
    const fell = wasEnabled.current && !enabled
    wasEnabled.current = enabled
    if (!fell) return
    setCals([])
    setWindows(new Map())
    setWindowFails(new Map())
    setLoaded(false)
    asked.current.clear()
    gen.current.clear()
    seeded.current = null
    latest.current = ''
  }, [enabled])

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

  const windowErrors = useCallback(
    (from: string, to: string): string[] => windowFails.get(windowKey(from, to)) ?? [],
    [windowFails])

  const value: CalendarData = {
    cals, loaded, setCals, eventsFor, requestWindow, setEvents, reload, windowErrors,
  }
  return <CalendarCtx.Provider value={value}>{children}</CalendarCtx.Provider>
}
