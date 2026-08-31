/**
 * The 2026-08-19 sweep, stage 3: silent data loss in the SPA.
 *
 * **All CLOSED.** Each of these was an `it.fails` pin asserting the behaviour
 * the app should have while failing against the code as it stood; the markers
 * are gone and these are ordinary regression tests now, which must stay green.
 * Same contract as `backlog.stage4.test.tsx`, whose api-mocking preamble this
 * copies.
 *
 * The original five are the sweep's; three more at the foot were filed by the
 * ADVERSARIAL REVIEW of this stage and closed later, which is why the create
 * double in the fourth test normalises the way the server does — it did not,
 * and that is precisely why `reconcileReplay`'s type mismatches were invisible
 * to it.
 *
 * The theme is one class of defect: state that overwrites or discards the
 * user's real data without saying so. Nothing here throws, nothing is logged
 * and nothing looks wrong on screen — a failed settings read that leaves the
 * defaults in place and then writes them back over the account, a manual drag
 * position clobbered by a task copied into a second list, folded trees pruned
 * against what happens to be rendered, a corrected bulk row replayed under its
 * old idempotency slug, and a calendar still painting the previous session's
 * events after a logout. In every case the user's own data is what is lost, and
 * the only evidence is the test.
 *
 * All five are BEHAVIOURAL: each drives the real component or the real function
 * and asserts the result a user or the API would see. None reads source text.
 * Where a finding could correctly be repaired in more than one shape, the
 * assertion names the outcome rather than the repair — STAGES.md records what
 * pins that only accept the fix you imagined cost the last time. That mattered
 * here: the bulk-composer finding allowed three repairs and the one taken (a
 * replayed create is reconciled against the body it was given, and the
 * difference sent as the PATCH it should have been) is not the one the
 * suggested fix leads with.
 */
import { useState } from 'react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { App } from './App'
import { DataProvider, useTaskData } from './data'
import { sortTasks } from './order'
import { TasksView } from './components/TasksView'
import { setCacheUser } from './cache'
import { api, HttpError, uidFor, type CalEvent, type List, type Task } from './api'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [], parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  // Present on every DTO the server sends; see api.ts's Task.
  completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
  created: null, last_modified: null,
 
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

const work: List = {
  id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: '#D9480F',
}
const home: List = { ...work, id: 'l2', href: '/l2/', name: 'Home', color: '#1565C0' }

let errSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  vi.clearAllMocks()
  // No cache user, so nothing seeds from the disk mirror and each test is cold.
  setCacheUser('')
  localStorage.clear()
  document.documentElement.dataset.theme = 'light'
  document.documentElement.removeAttribute('style')
  m.me.mockResolvedValue({ authenticated: true, user: 'owner' })
  m.getSettings.mockResolvedValue({})
  m.putSettings.mockResolvedValue({})
  m.logout.mockResolvedValue({})
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
  // createMany reports failures as indexes rather than raising N toasts; it
  // logs them, and a bulk pin below deliberately fails one.
  errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => errSpy.mockRestore())

/** Open the settings panel and, when named, drill into a section. Same shape as
 *  App.test.tsx's helper: the nav items are `role="tab"`, not buttons. */
const openSettings = async (section?: string) => {
  await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
  if (section) await userEvent.click(screen.getByRole('tab', { name: section }))
}

// ── the settings bootstrap ─────────────────────────────────────────────────

/** What the server does to a due value on the way back out: `_iso()` emits
 *  seconds, and a date-only due stays a date. The client sends
 *  `YYYY-MM-DDTHH:MM`. */
const normalizeDue = (due: string | null): string | null =>
  due && due.includes('T') && due.length === 16 ? `${due}:00` : due

/** ical/edit.py's PRIORITY map. `Task.priority` is the iCal INTEGER; the create
 *  body carries the label. */
const PRIORITY: Record<string, number | null> = {
  none: null, low: 9, medium: 5, high: 1,
}

describe('aug19 stage 3 — a failed settings read', () => {
  // -- AUDIT: App.tsx:203 — a failed GET /api/settings is swallowed silently,
  //    and the next preference gesture overwrites the account's stored settings
  //    with the shipped defaults --
  it('does not write a defaults-derived preference back over the account', async () => {
    /**
     * EVIDENCE. The settings bootstrap ends in
     * `.catch(() => { /* keep the locally-cached theme + appearance *\/ })`.
     * That comment holds for exactly two settings — theme and appearance have a
     * localStorage mirror. The other eleven (`hidden_calendars`,
     * `archived_calendars`, `hidden_lists`, `task_groups`, `collapsed_groups`,
     * `collapsed_tasks`, `dashboard`, `calendar_task_lists`, `tab_order`,
     * `start_tab`, `tasks_view`) have no mirror at all, so one failed read
     * leaves them at their shipped defaults with no toast, no error state and
     * no retry — the effect only re-runs on an `auth` transition, and a `rev`
     * bump does not re-run it.
     *
     * Every mutator then composes its PUT from that empty local state, so the
     * first gesture after the failed read replaces the account's whole stored
     * array with a default-derived one. The concrete loss: /api/settings 502s
     * once through the tunnel during a backend restart while /api/me (warm
     * worker) succeeds; five archived calendars reappear on the grid and three
     * sidebar groups vanish; the owner archives one calendar again and
     * `PUT {archived_calendars: ['c9']}` makes the other four permanent losses.
     *
     * The tab strip is the cheapest of the eleven to drive end to end, and it
     * loses the same way: with the read failed, `tabOrder` is DEFAULT_TAB_ORDER
     * and one click on "Move Calendar left" PUTs
     * `{tab_order: ['home','calendar','tasks','scheduling']}` — an order the
     * account never chose, over whatever it had stored.
     *
     * This is the read-side twin of two write-side findings already closed: the
     * settings writes that swallowed every failure including 401, and the
     * `listsOk` gate in data.tsx. Both added a real-fetch gate before anything
     * destructive; this path never got one.
     *
     * ASSERTED, deliberately, as the loss rather than the repair: after a
     * failed read, no whole-array preference derived from the defaults may
     * reach the server. Gating the mutators, holding the writes, retrying the
     * GET or disabling the editor all satisfy it; the pin does not care which,
     * and does not require a toast, because a fix that only made the failure
     * visible would not stop the overwrite.
     */
    m.getSettings.mockRejectedValue(new HttpError(502, 'bad gateway'))
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())

    await openSettings('General')
    await userEvent.click(screen.getByRole('button', { name: 'Move Calendar left' }))

    const wroteTabOrder = m.putSettings.mock.calls
      .map(([patch]) => patch)
      .filter((patch) => patch && 'tab_order' in patch)
    expect(wroteTabOrder).toEqual([])
  })
})

// ── the display order ──────────────────────────────────────────────────────

describe('aug19 stage 3 — sortTasks with a uid in two lists', () => {
  // -- AUDIT: order.ts:128 — sortTasks keys its effective-position map by bare
  //    uid, so one task copied into a second list silently rewrites another
  //    task's manual drag position --
  it('keeps a dragged row where it was dropped when a copy shares its uid', () => {
    /**
     * EVIDENCE. `sortTasks` gives every task ONE effective position in a
     * `Map<string, number>` keyed by `t.uid`. The array it is handed is the
     * merged multi-list set — data.tsx flattens `api.tasks(l.id)` over every
     * list — and the backend keys items on `(collection_href, uid)`, so the
     * same UID genuinely appears twice: copying a VTODO between lists in
     * Tasks.org, DAVx5 or Thunderbird preserves the UID, and the trust model
     * treats those clients as equal-rights writers.
     *
     * When one copy is placed by hand (`sort_order != null`) and the twin is
     * not, the unplaced-task loop overwrites the placed copy's entry, so the
     * row the user dragged jumps somewhere else on every render:
     *
     *     sortTasks([Alpha(pos 1), Bravo(pos 2), Charlie(pos 3), Zulu(uid 'a')])
     *       -> ['l1/Bravo', 'l1/Charlie', 'l1/Alpha', 'l2/Zulu']
     *
     * Alpha was dragged to the top; because the Home copy carrying its UID
     * sorts after everything intrinsically, `at` gets 'a' -> 3 and Alpha falls
     * to third. Nothing the user does in the Work list can fix it, and it is
     * not cosmetic: data.tsx builds the POST /api/tasks/reorder payload from
     * `sortTasks(tasks)`, so the next drag persists the scrambled sequence for
     * the whole account. order.test.ts has no case with two tasks sharing a
     * uid.
     *
     * Asserted on the placed rows' relative order only — where the twin itself
     * lands is a judgement call any correct fix may make differently.
     */
    const alpha = task({ uid: 'a', list: 'l1', sort_order: 1, summary: 'Alpha' })
    const bravo = task({ uid: 'b', list: 'l1', sort_order: 2, summary: 'Bravo' })
    const charlie = task({ uid: 'c', list: 'l1', sort_order: 3, summary: 'Charlie' })
    // The Home copy: same UID, different collection, never dragged.
    const twin = task({ uid: 'a', list: 'l2', summary: 'Zulu (Home copy of Alpha)' })

    const out = sortTasks([alpha, bravo, charlie, twin])
      .map((t) => `${t.list}/${t.summary}`)
    expect(out.filter((row) => row.startsWith('l1/')))
      .toEqual(['l1/Alpha', 'l1/Bravo', 'l1/Charlie'])
  })
})

// ── folded subtask trees ───────────────────────────────────────────────────

describe('aug19 stage 3 — folding a tree while another list is hidden', () => {
  /** TasksView with two lists, one of them hidden, and a controlled
   *  `collapsedTasks` fed back exactly the way App holds it. */
  function setup(collapsedTasks: string[], hiddenLists: string[]) {
    const onCollapsedTasksChange = vi.fn()
    const Harness = () => {
      const [collapsed, setCollapsed] = useState(collapsedTasks)
      return (
        <DataProvider rev={0} onExpire={vi.fn()}>
          <TasksView onExpire={vi.fn()} view="list" onView={vi.fn()}
            sideCollapsed={false} onToggleSide={vi.fn()}
            hiddenLists={hiddenLists} onHiddenListsChange={vi.fn()}
            groups={[]} onGroupsChange={vi.fn()}
            collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
            collapsedTasks={collapsed}
            onCollapsedTasksChange={(next) => { onCollapsedTasksChange(next); setCollapsed(next) }}
            showCompleted={false} />
        </DataProvider>
      )
    }
    render(<Harness />)
    return { onCollapsedTasksChange, user: userEvent.setup() }
  }

  // -- AUDIT: TasksView.tsx:297 — folding one subtask tree silently deletes the
  //    folded state of every tree that is not currently rendered, and the loss
  //    is written to the server --
  it('keeps a hidden list’s folded trees when another tree is folded', async () => {
    /**
     * EVIDENCE. `setCollapsed` prunes the account-synced `collapsed_tasks` set
     * against `kidRows`, which the comment above it calls "uids that still name
     * a task with children". It is not that. `kidRows` is built from
     * `shownTasks` (hidden lists filtered out) and only for rows where
     * `parentIsRendered(t)` holds, which consults `showCompleted`. So it means
     * "uids with a child RENDERED RIGHT NOW". Any folded tree in a hidden list,
     * or whose parent is completed while the default `showCompleted={false}` is
     * in force, is absent from `kidRows` and is dropped the moment the user
     * folds or unfolds anything else.
     *
     * `onCollapsedTasksChange` goes straight to `App.changeCollapsedTasks` ->
     * `saveSettingsSoon({collapsed_tasks: next})`, so the loss is persisted to
     * the account, survives a reload and follows the user to another browser.
     * Hide the Home list, fold a couple of Work trees, unhide Home — every Home
     * tree you had folded is expanded again, permanently.
     *
     * Here: lists Work (l1) and Home (l2), `hiddenLists=['l2']`, a parent with
     * a child in each, and 'h1' already folded. Clicking "Hide subtasks of Work
     * parent" calls back with `['w1']` — 'h1' is gone. The completed-parent case
     * is the same line and the same failure: with `showCompleted={false}`, a
     * folded tree whose parent is done is pruned away just as silently.
     *
     * The map the comment actually describes, `kidsByParent`, is built from all
     * `tasks` and is already in scope — but the assertion is on the set that
     * comes back, so any fix that stops discarding an off-screen tree passes.
     * Compared unordered, since nothing about the finding is about order.
     */
    m.lists.mockResolvedValue([work, home])
    m.tasks.mockImplementation(async (listId: string) => (listId === 'l1'
      ? [
        task({ uid: 'w1', list: 'l1', summary: 'Work parent', href: '/l1/w1.ics' }),
        task({ uid: 'w2', list: 'l1', summary: 'Work child', parent: 'w1', href: '/l1/w2.ics' }),
      ]
      : [
        task({ uid: 'h1', list: 'l2', summary: 'Home parent', href: '/l2/h1.ics' }),
        task({ uid: 'h2', list: 'l2', summary: 'Home child', parent: 'h1', href: '/l2/h2.ics' }),
      ]))

    const { user, onCollapsedTasksChange } = setup(['h1'], ['l2'])
    await screen.findByText('Work parent')
    // The Home list is hidden, so its folded tree is nowhere on screen.
    expect(screen.queryByText('Home parent')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Hide subtasks of Work parent' }))

    expect(onCollapsedTasksChange).toHaveBeenCalled()
    const calls = onCollapsedTasksChange.mock.calls
    const next = calls[calls.length - 1][0] as string[]
    // The Home tree's entry survives — that is the whole finding — and the Work
    // tree gains one. Asserted as membership rather than as an exact list,
    // because the STORED SPELLING changed when the pane was re-keyed on
    // (list, uid): a fold is now written as `taskKey`, and a bare uid saved by
    // an earlier version is honoured and kept until the user toggles it. What
    // this pin is about — an off-screen folded tree not being discarded — is
    // untouched by that, and pinning the literal would have made it a test of
    // the wire format instead.
    expect(next, "the hidden list's folded tree was discarded").toContain('h1')
    expect(next.some((x) => x === 'w1' || x.endsWith('\u0000w1')),
      `the tree just folded is not in ${JSON.stringify(next)}`).toBe(true)
    expect(next).toHaveLength(2)
  })
})

// ── the bulk composer's retry ──────────────────────────────────────────────

describe('aug19 stage 3 — correcting a bulk row before a retry', () => {
  // -- AUDIT: AddMultipleModal.tsx:298 — a bulk row corrected in any field
  //    except its title replays the old client_id, so the correction is
  //    silently discarded and the modal reports success --
  it('does not close reporting success on a correction the server drops', async () => {
    /**
     * EVIDENCE. `patchRow` mints a fresh idempotency id only when `summary`
     * changes. Every other property a row carries — due date/time, start,
     * priority, tags, notes, list — and the whole shared strip (read fresh in
     * `submit`) can be edited between attempts while the row keeps its original
     * `cid`. The backend answers a replayed slug by confirming the resource
     * already written under it (`sync/engine.py:_put_new` swallows the 412 when
     * the occupant carries the same UID, and `service.create_task` returns
     * `get_task(...)` — the existing resource, unmodified). So on the exact
     * failure this retry flow exists for — the POST landed, the response was
     * lost over the tunnel — the corrected values never reach the server,
     * `settleCreate` paints the server's old DTO, `bad` is empty, and the modal
     * closes as though everything landed.
     *
     * Driven end to end through TasksView so the real `createMany` is the
     * modal's `onSubmit` and `api.createTask` is the seam: the mock below is a
     * miniature of the backend's rule — first write under a slug wins, a replay
     * is answered with the stored resource. Three rows, shared due 2026-08-10;
     * row 2's response is lost. The user assumes the date was the problem,
     * changes the shared due to 2026-08-11 and presses Add. The retry POSTs the
     * new body under the old slug, the server confirms DUE 2026-08-10, and the
     * modal closes on a success it did not get.
     *
     * ASSERTED as the conjunction that is the defect, so that each of the
     * repairs the finding allows breaks it: the modal OFFERED the correction,
     * the account still holds the old value, and the modal reported success.
     * Following the replay with a PATCH of the diff clears the second; freezing
     * a kept row's non-title fields clears the first; keeping the modal open
     * with the row still failed clears the third. Regenerating the cid is not
     * one of them — it would author a duplicate on a lost response, which is
     * the bug the cid exists to prevent.
     *
     * One thing the double cannot model yet: today's POST gives no sign that it
     * was a replay, so it answers one exactly as the server does. A fix that
     * adds that signal has to teach this mock to emit it — the assertion below
     * is unchanged either way, since it is about the account's due date and the
     * dialog, not about how the client learned.
     */
    const listId = 'l1'
    m.lists.mockResolvedValue([work])
    m.tasks.mockResolvedValue([])

    // A miniature of the CalDAV slug rule: the resource written under a
    // client_id is what a replay is answered with, body ignored.
    //
    // WIDENED to normalise the way the server does — see `normalizeDue` /
    // `PRIORITY` above. The original echoed `body.due` verbatim and never
    // returned a numeric priority, so `reconcileReplay`'s type mismatches were
    // invisible to it: every bulk row with a timed due or a priority provoked a
    // spurious PATCH and no test could see it.
    const server = new Map<string, Task>()
    let loseOnce = 'Pack the kitchen'
    m.createTask.mockImplementation(async (list: string, body: Record<string, unknown>) => {
      const cid = body.client_id as string
      if (!server.has(cid)) {
        const label = (body.priority as string) ?? 'none'
        server.set(cid, task({
          uid: uidFor(cid), list, summary: body.summary as string,
          due: normalizeDue((body.due as string) ?? null),
          priority: PRIORITY[label] ?? null, priority_label: label,
          href: `/${list}/${cid}.ics`,
        }))
      }
      if (body.summary === loseOnce) {           // the write landed; the reply did not
        loseOnce = ''
        throw new HttpError(502, 'bad gateway')
      }
      return server.get(cid)!
    })
    // Available to any fix that follows a replay with a correction.
    m.patchTask.mockImplementation(async (list: string, uid: string, patch: Record<string, unknown>) => {
      const entry = [...server.entries()].find(([, t]) => t.uid === uid)
      if (!entry) throw new HttpError(404, 'no such task')
      const next = {
        ...entry[1],
        ...(('due' in patch) ? { due: normalizeDue((patch.due as string) ?? null) } : {}),
      }
      server.set(entry[0], next)
      return next
    })

    const user = userEvent.setup()
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TasksView onExpire={vi.fn()} view="list" onView={vi.fn()}
          sideCollapsed={false} onToggleSide={vi.fn()}
          hiddenLists={[]} onHiddenListsChange={vi.fn()}
          groups={[]} onGroupsChange={vi.fn()}
          collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
          collapsedTasks={[]} onCollapsedTasksChange={vi.fn()}
          showCompleted={false} />
      </DataProvider>,
    )

    await user.click(await screen.findByRole('button', { name: 'New…' }))
    await screen.findByRole('dialog', { name: 'Add task' })
    await user.click(screen.getByRole('button', { name: 'Add multiple' }))
    await screen.findByRole('dialog', { name: /add multiple tasks/i })

    for (const [i, t] of ['Book the van', 'Pack the kitchen', 'Cancel the paper'].entries()) {
      await user.clear(screen.getByLabelText(`Title, row ${i + 1}`))
      await user.type(screen.getByLabelText(`Title, row ${i + 1}`), t)
    }
    await user.type(screen.getByLabelText('Due date, for all tasks'), '2026-08-10')
    await user.click(screen.getByRole('button', { name: 'Add 3 tasks' }))

    // Row 2 came back failed and was kept, carrying its original slug.
    await screen.findByRole('alert')
    expect(screen.getByLabelText('Title, row 1')).toHaveValue('Pack the kitchen')
    const replayed = m.createTask.mock.calls
      .find(([, body]) => body.summary === 'Pack the kitchen')![1].client_id as string

    // The user blames the date and corrects it — if the modal still lets them.
    const due = screen.getByLabelText('Due date, for all tasks') as HTMLInputElement
    const correctionOffered = !due.disabled
    if (correctionOffered) fireEvent.change(due, { target: { value: '2026-08-11' } })
    await user.click(screen.getByRole('button', { name: 'Add 1 task' }))
    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(4))

    const dueOnTheAccount = server.get(replayed)?.due ?? null
    const reportedSuccess =
      screen.queryByRole('dialog', { name: /add multiple tasks/i }) === null
    // Spelled out rather than compared as a tuple, so the failure prints what
    // actually happened. Any one of the three clauses being false is a fix.
    const verdict = correctionOffered && dueOnTheAccount !== '2026-08-11' && reportedSuccess
      ? 'the composer took the corrected due date, closed reporting success, and left'
        + ` the account holding due ${dueOnTheAccount}`
      : 'no silent loss'
    expect(verdict).toBe('no silent loss')
  })
})

// ── the data mirror across a session boundary ──────────────────────────────

describe('aug19 stage 3 — logging out and back in', () => {
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

  const cal: List = {
    id: 'c1', href: '/c1/', name: 'Work', is_task_list: false, is_calendar: true,
    open_count: 0, task_count: 0, event_count: 1, total: 1, color: '#D9480F',
  }

  /** One event, today, so it lands inside whatever month grid the app opens on. */
  const todaysEvent = (summary: string): CalEvent => {
    const day = iso(new Date())
    return {
      uid: 'e1', id: 'e1', recurrence_id: null, is_recurring: false, calendar: '/c1/',
      summary, description: null, location: null,
      start: `${day}T09:00:00`, start_is_date: false,
      end: `${day}T09:30:00`, end_is_date: false, duration: null,
      all_day: false, status: null, busy: true, notify_minutes_before: null, tags: [], has_rrule: false,
      href: '/c1/e1.ics', etag: '"1"',
    }
  }

  // -- AUDIT: data.tsx:505 — logout does not clear the in-memory data mirror,
  //    so the calendar keeps painting the previous session's events and never
  //    refetches them --
  it('does not paint the previous session’s events to the next one', async () => {
    /**
     * EVIDENCE. `onLogout` deliberately calls `clearCache()` + `setCacheUser('')`
     * so the disk mirror cannot outlive a session — cache.ts is user-keyed and
     * version-keyed for exactly that. But `DataProvider` sits ABOVE the auth
     * branch on purpose, so it never unmounts, and nothing resets its state
     * when `enabled` goes false: `CalendarProvider`'s `cals`, `windows`,
     * `asked` and `gen` survive a logout intact. On the next login CalendarView
     * remounts, `eventsFor` hits `windows` and paints the previous session's
     * rows, and `requestWindow` short-circuits because `asked.get(key)` still
     * equals `${rev}|${calIds}` — so the month is never refetched at all.
     * `TaskProvider` does refetch (its effects list `enabled` as a dep), which
     * makes the calendar's behaviour an inconsistency rather than a design.
     *
     * Reproduced here against the real App with only ./api mocked, start_tab
     * 'calendar': sign in as alice with one event on the grid, log out through
     * Settings > Account (so `clearCache()` really runs and the login card
     * really shows), sign back in as bob with `api.events` now resolving []. The
     * chip is still there and `api.events` was never called a second time.
     *
     * In the multi-user reading of the threat model this serves account A's
     * events to account B; in the single-user one it means "log out at night,
     * log back in in the morning" shows a frozen snapshot that misses
     * everything DAVx5 or Apple Calendar wrote overnight. No App.test.tsx case
     * renders a view across a logout/login cycle, so the suite is green.
     *
     * Asserted on both halves, because clearing the painted rows without
     * clearing `asked` would leave the grid permanently empty instead: the old
     * event must be gone, and the window must be asked for again.
     */
    m.me.mockResolvedValue({ authenticated: true, user: 'alice' })
    m.getSettings.mockResolvedValue({ start_tab: 'calendar' })
    m.calendars.mockResolvedValue([cal])
    m.events.mockResolvedValue([todaysEvent('ALICE SECRET')])
    m.login.mockResolvedValue({ authenticated: true, user: 'bob' })

    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('ALICE SECRET')
    const eventFetches = m.events.mock.calls.length
    const calFetches = m.calendars.mock.calls.length

    await openSettings('Account')
    await user.click(screen.getByRole('button', { name: /log out/i }))
    await screen.findByRole('button', { name: /sign in/i })

    // A different account signs in, and it has no events at all.
    // The login card labels its fields with plain <label>s, so query them the
    // way Login.test.tsx does.
    m.events.mockResolvedValue([])
    await user.type(screen.getAllByRole('textbox')[0], 'bob')
    await user.type(document.querySelector('input[type="password"]')!, 'hunter2')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await screen.findByRole('button', { name: 'Calendar' })
    await waitFor(() =>
      expect(m.calendars.mock.calls.length).toBeGreaterThan(calFetches))
    expect(screen.queryByText('ALICE SECRET')).not.toBeInTheDocument()
    await waitFor(() =>
      expect(m.events.mock.calls.length).toBeGreaterThan(eventFetches))
  })
})


/** Exposes the provider's actions to the test. */
function Probe3({ onReady }: { onReady: (d: ReturnType<typeof useTaskData>) => void }) {
  const d = useTaskData()
  onReady(d)
  return <div />
}

// ── Filed by the Stage 3 adversarial review — OPEN when written ─────────────

describe('2026-08-20 review — the settings write path', () => {
  it('writes no setting computed from a read that failed', async () => {
    // MERGED_SETTINGS gates the read-modify-write preferences behind a failed
    // load, and its rationale — scalars are safe because "the value they carry
    // is the one just chosen" — is false for CYCLING controls, which are
    // read-modify-write over exactly the state that failed to load.
    //
    // `session_ttl_s` cycles. With the read failed, `sessionTtl` is null, the
    // panel reads "7 days" whatever the account holds, and ONE click PUTs 30
    // days — a 30x lengthening of the field app.py calls out as
    // security-relevant, silently, from a label that was already lying.
    //
    // Asserted as the OUTCOME: nothing about the session length reaches the API
    // while the read is broken. Suppressing the write, disabling the control, or
    // both, all satisfy it.
    m.me.mockResolvedValue({ authenticated: true, user: 'admin' })
    m.getSettings.mockRejectedValue(new HttpError(502, 'bad gateway'))
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await openSettings('Account')

    const ttl = await screen.findByLabelText('How long to stay signed in')
    await user.click(ttl)
    await act(async () => { await Promise.resolve() })

    const wroteTtl = m.putSettings.mock.calls
      .map((c) => c[0] as Record<string, unknown>)
      .filter((b) => 'session_ttl_s' in b)
    expect(wroteTtl, 'a failed read let one click rewrite the session length').toEqual([])
  })

  it('writes no home timezone computed from a read that failed', async () => {
    // WIDENING. The pin above drives `session_ttl_s` and the one below drives
    // `appearance`; `home_timezone` is the third setting the finding names and
    // nothing drove it. An adversarial review shipped the list with
    // `session_ttl_s` and `appearance` in it and `home_timezone` left out — the
    // whole suite stayed green, and the checked half-fix ("`session_ttl_s`
    // alone") does not reach it either.
    //
    // It is the one of the three with a consequence outside the account.
    // `toggleHomeTz` is `homeTz ? '' : Intl…resolvedOptions().timeZone`, pure
    // read-modify-write over the state the read was supposed to populate: with
    // the read broken `homeTz` is '', the row reads "Not set" whatever the
    // account holds, and one click replaces the stored zone with the LAPTOP's.
    // `busy_intervals` resolves floating times through that zone, so the public
    // booking page's busy set moves by the offset — hours the owner really has
    // appointments in become bookable by strangers.
    m.me.mockResolvedValue({ authenticated: true, user: 'admin' })
    m.getSettings.mockRejectedValue(new HttpError(502, 'bad gateway'))
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await openSettings('General')

    const tz = await screen.findByLabelText('Timezone your events are written in')
    await user.click(tz)
    await act(async () => { await Promise.resolve() })

    const wroteTz = m.putSettings.mock.calls
      .map((c) => c[0] as Record<string, unknown>)
      .filter((b) => 'home_timezone' in b)
    expect(wroteTz,
      "a failed read let one click rewrite the booking page's busy-set zone")
      .toEqual([])
  })

  it('writes no clock or density toggle computed from a read that failed', async () => {
    // The same finding, applied to the CLASS rather than to the three settings
    // it named. `time_format`, `sidebar_collapsed`, `show_completed_tasks`,
    // `calendar_show_done_tasks` and `calendar_fit` are every one of them
    // `next = !current` / `nextX(current)` over state this read populates, so a
    // failed read makes the row show the shipped default and one press write
    // the NEGATION of a lie over whatever the account held. Lower stakes than
    // the session length or the booking zone, but the same defect and the same
    // rule, and the rule is what the list says it implements.
    //
    // Driven through the clock, which is the one of the five that changes every
    // surface in the app at once.
    m.me.mockResolvedValue({ authenticated: true, user: 'admin' })
    m.getSettings.mockRejectedValue(new HttpError(502, 'bad gateway'))
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await openSettings('General')

    await user.click(await screen.findByLabelText('12- or 24-hour clock'))
    await act(async () => { await Promise.resolve() })

    const wrote = m.putSettings.mock.calls
      .map((c) => c[0] as Record<string, unknown>)
      .filter((b) => 'time_format' in b)
    expect(wrote, 'a failed read let one click flip the clock for the account')
      .toEqual([])
  })

  it('still writes every one of those settings when the read succeeded', async () => {
    // The control for all four pins above, and the one that matters most: the
    // gate is a REFUSAL, and a refusal that fires when it should not makes the
    // whole settings panel inert. `settingsFailed` is a ref set in the read's
    // catch, so a fix that set it eagerly, or forgot to leave it false on the
    // happy path, would be invisible to every pin here — they all drive a
    // FAILED read.
    m.me.mockResolvedValue({ authenticated: true, user: 'admin' })
    m.getSettings.mockResolvedValue({ home_timezone: 'Europe/Berlin' })
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await openSettings('General')

    await user.click(await screen.findByLabelText('12- or 24-hour clock'))
    await user.click(await screen.findByLabelText('Timezone your events are written in'))
    await act(async () => { await Promise.resolve() })

    const keys = new Set(m.putSettings.mock.calls
      .flatMap((c) => Object.keys(c[0] as Record<string, unknown>)))
    expect(keys, 'a successful read still refused the clock').toContain('time_format')
    expect(keys, 'a successful read still refused the timezone').toContain('home_timezone')
  })

  it('writes no appearance object that would destroy the theme collection', async () => {
    // `appearance` was excused in the original pin's own evidence as having a
    // localStorage mirror — but `cacheAppearance` REMOVES the mirror whenever no
    // theme is active. So an account with saved themes and none active starts
    // from `{}`, and `selectTheme` produces literally `{active: id}` with no
    // `themes` key. `update_settings` does `current.update(patch)` — a shallow
    // replace — so the account's whole theme collection is destroyed by picking
    // a theme.
    //
    // Asserted as the outcome: nothing is written, or what is written still
    // carries the themes. Both are safe; a bare `{active}` is not.
    m.me.mockResolvedValue({ authenticated: true, user: 'admin' })
    m.getSettings.mockRejectedValue(new HttpError(502, 'bad gateway'))
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await openSettings('Appearance')
    await user.click(await screen.findByLabelText('Customize appearance'))

    const picker = await screen.findByRole('combobox', { name: 'Theme' })
    const options = within(picker).getAllByRole('option')
      .map((o) => (o as HTMLOptionElement).value).filter(Boolean)
    expect(options.length, 'no theme to select').toBeGreaterThan(0)
    await user.selectOptions(picker, options[0])
    // `changeAppearance` goes through `saveSettingsSoon`, which debounces 400ms.
    // Waited out rather than waited FOR: once the gate holds the write there is
    // no PUT to wait for, and `waitFor(putSettings called)` would fail on the
    // fixed rather than on the bug. Real timers here — this file uses them.
    await act(async () => { await new Promise((r) => setTimeout(r, 700)) })

    const wrote = m.putSettings.mock.calls
      .map((c) => c[0] as Record<string, unknown>)
      .filter((b) => 'appearance' in b)
    for (const body of wrote) {
      const appearance = body.appearance as Record<string, unknown>
      expect(Array.isArray(appearance?.themes),
        `PUT ${JSON.stringify(body)} would replace the theme collection`).toBe(true)
    }
    expect(wrote.length === 0 || wrote.every(
      (b) => Array.isArray((b.appearance as Record<string, unknown>)?.themes))).toBe(true)
  })

  it('sends no correction for a bulk row the server merely normalised', async () => {
    // `reconcileReplay` runs after EVERY `api.createTask` in a bulk add, and two
    // of its comparisons are type-mismatched against the real DTO:
    // `CreateTaskBody.priority` is a LABEL ('high') while `Task.priority` is the
    // iCal INTEGER (1), and `body.due` is `YYYY-MM-DDTHH:MM` while the server
    // returns `_iso()` output with seconds. So every row with a timed due or a
    // priority looks like a replay of a different body and provokes a PATCH — a
    // 20-row add becomes 40 writes, each a CalDAV PUT with a SEQUENCE bump every
    // other client sees.
    //
    // Its own comment claims "a server-side normalisation of something we left
    // alone cannot provoke a write". Normalisation of the fields we DID set is
    // exactly what provokes it.
    //
    // Worse, the reconcile sits inside `createMany`'s try, so a transient
    // failure on that redundant PATCH marks a create that fully landed as a
    // failed row — the composer keeps it, and the user adds it twice.
    m.lists.mockResolvedValue([work])
    m.tasks.mockResolvedValue([])
    const server = new Map<string, Task>()
    m.createTask.mockImplementation(async (list: string, body: Record<string, unknown>) => {
      const cid = body.client_id as string
      const label = (body.priority as string) ?? 'none'
      if (!server.has(cid)) {
        server.set(cid, task({
          uid: uidFor(cid), list, summary: body.summary as string,
          due: normalizeDue((body.due as string) ?? null),
          priority: PRIORITY[label] ?? null, priority_label: label,
          href: `/${list}/${cid}.ics`,
        }))
      }
      return server.get(cid)!
    })

    let d!: ReturnType<typeof useTaskData>
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <Probe3 onReady={(x) => { d = x }} />
      </DataProvider>,
    )
    await waitFor(() => expect(m.tasks).toHaveBeenCalled())

    await act(async () => {
      await d.createMany(
        [{ listId: 'l1', cid: 'row-1',
          body: { summary: 'Call the vet', due: '2026-08-10T09:30', priority: 'high' } }],
        () => {},
      )
    })

    expect(m.createTask).toHaveBeenCalledTimes(1)
    expect(m.patchTask.mock.calls, 'the server normalised what we sent and we "corrected" it')
      .toEqual([])
  })
})

describe('2026-08-21 review — regressions found in the Stage 4 fixes', () => {
  it('does not resolve createMany while a correction is still in flight', async () => {
    // AddMultipleModal closes the instant `onSubmit` resolves, so detaching the
    // reconcile opened a window where the user is looking at a row whose second
    // `settleCreate` has not landed. Tick its box, or delete it, and the older
    // server DTO is written back over them — and `settleCreate` re-appends a row
    // that was deleted in that window.
    //
    // Asserted as the outcome: nothing is still pending when the batch resolves.
    m.lists.mockResolvedValue([work])
    m.tasks.mockResolvedValue([])
    let patchPending = false
    m.createTask.mockImplementation(async (list: string, body: Record<string, unknown>) =>
      task({
        uid: uidFor(body.client_id as string), list,
        summary: body.summary as string,
        due: normalizeDue((body.due as string) ?? null),
        // Deliberately NOT normalised, so a correction really is provoked.
        priority: null, priority_label: 'none',
      }))
    m.patchTask.mockImplementation(async () => {
      patchPending = true
      await new Promise((r) => setTimeout(r, 30))
      patchPending = false
      return task({ uid: 'x' })
    })

    let d!: ReturnType<typeof useTaskData>
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <Probe3 onReady={(x) => { d = x }} />
      </DataProvider>,
    )
    await waitFor(() => expect(m.tasks).toHaveBeenCalled())

    await act(async () => {
      await d.createMany(
        [{ listId: 'l1', cid: 'r1', body: { summary: 'Call the vet', priority: 'high' } }],
        () => {},
      )
    })

    expect(m.patchTask).toHaveBeenCalledTimes(1)
    expect(patchPending,
      'createMany resolved — and the modal closed — while a correction was still in flight')
      .toBe(false)
  })

  it('sends no correction for a bulk row whose START the server merely normalised', async () => {
    // The same shape mismatch as `due`, one field over: `bodyFrom` emits
    // `start: 'YYYY-MM-DDTHH:MM'` and `_iso()` returns it with seconds. Missed
    // when `due` was fixed because the widened double never drove a timed start.
    m.lists.mockResolvedValue([work])
    m.tasks.mockResolvedValue([])
    m.createTask.mockImplementation(async (list: string, body: Record<string, unknown>) =>
      task({
        uid: uidFor(body.client_id as string), list,
        summary: body.summary as string,
        start: normalizeDue((body.start as string) ?? null),
      }))

    let d!: ReturnType<typeof useTaskData>
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <Probe3 onReady={(x) => { d = x }} />
      </DataProvider>,
    )
    await waitFor(() => expect(m.tasks).toHaveBeenCalled())

    await act(async () => {
      await d.createMany(
        [{ listId: 'l1', cid: 'r1',
           body: { summary: 'Pack', start: '2026-08-10T09:30' } }],
        () => {},
      )
    })

    expect(m.patchTask.mock.calls,
      'the server merely normalised `start` and we "corrected" it').toEqual([])
  })
})
