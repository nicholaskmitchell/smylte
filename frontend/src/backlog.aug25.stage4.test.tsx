/**
 * The 2026-08-25 sweep, stage 4: user-visible correctness & rendering.
 *
 * Something on screen is wrong, missing, or unreachable — and unlike stage 3 the
 * user can SEE it, which is the only reason it sorts lower. Ten of the stage's
 * thirteen findings are here; three need a real cascade and live in
 * `backlog.aug25.stage4.browser.test.tsx` on the tier from `bcf38cf`, and one
 * gets no pin at all (see docs/STAGES.md).
 *
 * **These findings are OPEN.** Every pin below is `it.fails`: it asserts the
 * CORRECTED behaviour and fails against the code as it stands, so the suite
 * stays green while the bug is open and goes red the moment it is fixed and the
 * pin needs reclassifying. Tests NOT marked `it.fails` are CONTROLS.
 *
 * Two shapes recur here, and both are about a failure the app cannot tell from
 * an absence. **Three findings turn a fetch failure into a confident lie** — one
 * bad list empties every task pane, a 502 on `/api/me` shows a sign-in card, a
 * failed day read shows a blank day — and the disk mirror, which exists exactly
 * so those cases still have something to show, is cleared on mount. **Three are
 * an affordance that is not there**: an indicator pointing at the wrong gap, a
 * grid no keyboard can reach, a stale alert over a fresh choice.
 *
 * Where a finding has more than one correct repair the assertion names the
 * OUTCOME. Two here are deliberately written as "these two renders must
 * DIFFER" or "this exact sentence must no longer appear", because the repair
 * chooses a class name or a wording and a pin has no business doing that.
 */
import { useState } from 'react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { App } from './App'
import { DataProvider, useCalendarData } from './data'
import { cacheCalendars, cacheLists, readCachedCalendars, setCacheUser } from './cache'
import { BookingPage } from './components/BookingPage'
import { CalendarView } from './components/CalendarView'
import { HomeView } from './components/HomeView'
import { TasksView } from './components/TasksView'
import { TodayView } from './components/TodayView'
import { type DashboardModule } from './dashboard'
import { api, AuthError, HttpError, type CalEvent, type DayEntry, type DayPlan,
  type List, type PublicBookingInfo, type Task } from './api'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)

// ── fixtures ───────────────────────────────────────────────────────────────

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [], parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  completed_at: null, kanban_column: null, estimated_minutes: null, has_rrule: false,
  created: null, last_modified: null,
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

const good: List = {
  id: 'good', href: '/good/', name: 'Home', is_task_list: true, is_calendar: false,
  open_count: 2, task_count: 2, event_count: 0, total: 2, color: '#D9480F',
}
const poison: List = { ...good, id: 'poison', href: '/poison/', name: 'Shared', color: '#1565C0' }
const cal: List = {
  id: 'c1', href: '/c1/', name: 'Personal', is_task_list: false, is_calendar: true,
  open_count: 0, task_count: 0, event_count: 1, total: 1, color: '#1971C2',
}

const ev = (o: Partial<CalEvent> = {}): CalEvent => ({
  uid: 'u1', id: 'u1', recurrence_id: null, is_recurring: false, calendar: '/c1/',
  summary: 'Standup', description: null, location: null,
  start: '2026-03-09T09:00:00', start_is_date: false,
  end: '2026-03-09T09:30:00', end_is_date: false, duration: null,
  all_day: false, status: null, tags: [], has_rrule: false,
  href: '/c1/u1.ics', etag: '"1"', ...o,
})

const pad = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const today = () => ymd(new Date())

const dayEntry = (o: Partial<DayEntry> = {}): DayEntry => ({
  entry_id: 'e1', day: today(), kind: 'note', list: null, uid: null,
  title: 'Water the plants', source: 'user', position: 1,
  done_at: null, dropped_at: null, habit_id: null, estimate_minutes: null,
  rolled_to: null, created_at: '2026-08-21T08:00:00.000Z', ...o,
})

const plan = (entries: DayEntry[] = [], day = today(), o: Partial<DayPlan> = {}): DayPlan => ({
  day, planned: true, entries, capacity_minutes: null, capacity: null,
  committed_at: null, shutdown_at: null, reflection: null, ...o,
})

let errSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  vi.clearAllMocks()
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
  m.openDay.mockResolvedValue(plan())
  m.day.mockImplementation(async (d) => plan([], d))
  m.days.mockResolvedValue([])
  m.habits.mockResolvedValue([])
  m.patchDay.mockImplementation(async (d, body) => plan([], d, body as Partial<DayPlan>))
  m.patchDayEntry.mockImplementation(async (_d, id) => dayEntry({ entry_id: id }))
  m.rollDayEntry.mockImplementation(async (_d, id, to) => dayEntry({ entry_id: id, rolled_to: to }))
  m.addDayEntry.mockImplementation(async (d, body) => dayEntry({
    entry_id: body.entry_id ?? 'e-new', day: d, kind: body.kind,
    list: body.list ?? null, uid: body.uid ?? null, title: body.title ?? null, position: 9,
  }))
  // Every pin here rejects a fetch on purpose; `makeGuard` logs each one.
  errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => errSpy.mockRestore())

// ════════════════════════════════════════════════════════════════════════════
// data.tsx — the two fetches that answer a failure with an absence
// ════════════════════════════════════════════════════════════════════════════

describe('2026-08-25 — one task list that will not load', () => {
  const rows = () =>
    [...document.querySelectorAll('.task:not(.sub) .task-title')].map((n) => n.textContent?.trim())

  function setup() {
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
  }

  const HEALTHY = [
    task({ uid: 'a', list: 'good', summary: 'Alpha', href: '/good/a.ics' }),
    task({ uid: 'b', list: 'good', summary: 'Bravo', href: '/good/b.ics' }),
  ]

  // ── AUDIT (open): data.tsx:217 — one failing task list blanks the whole
  //    account's tasks; every pane then says "Nothing to do here." ──────────
  it.fails('still shows the lists that answered', async () => {
    // EVIDENCE. `TaskProvider` fans the fetch out with
    // `await Promise.all(lists.map((l) => api.tasks(l.id)))`, so a single list
    // that answers 500/502/429/404 rejects the whole batch. `setTasks` is never
    // called, `loaded` is still flipped true in the `.finally`, and `guard`
    // raises one generic toast that does not name the list. Every task surface
    // in the app — TasksView, HomeView, TodayView, the calendar's task overlay —
    // reads that one array, so all of them go empty at once, and TasksView then
    // renders `{loaded ? 'Nothing to do here.' : 'Loading…'}`: the owner is told
    // their account is empty.
    //
    // The calendar path immediately below (data.tsx:711) was explicitly
    // rewritten to `Promise.allSettled` + per-calendar `windowErrors` for
    // exactly this shape. The task path never was, and there is no
    // reload/retry affordance on the tasks side at all: the effect re-runs on
    // `loadKey`/`rev`/`enabled`/`listsLoaded`, and `rev` only moves when the
    // server publishes a change — so on an idle account the empty pane is
    // permanent until a full page reload.
    //
    // The trigger is ordinary: one poison VTODO written by jtx Board or
    // Tasks.org that 500s the DTO builder for its collection, a documented
    // failure class in this repo.
    //
    // ASSERTED AS THE OUTCOME: a list that answered still shows its tasks.
    // `allSettled` plus a per-list error, a retry, or holding the previous rows
    // all satisfy it; the pin does not require a particular error surface,
    // because a fix that only made the failure visible would still have thrown
    // the healthy list's rows away.
    m.lists.mockResolvedValue([good, poison])
    m.tasks.mockImplementation(async (listId: string) => {
      if (listId === 'poison') throw new HttpError(500, 'internal error')
      return HEALTHY
    })
    setup()
    await waitFor(() => expect(m.tasks).toHaveBeenCalledTimes(2))

    await waitFor(() => expect(rows()).toEqual(['Alpha', 'Bravo']))
  })

  // CONTROL (passes today, must keep passing). With every list healthy the pane
  // renders both lists' rows. This is what proves the harness can render
  // anything at all — without it the pin above would be satisfied by a fan-out
  // that never returns.
  it('renders every list when they all answer', async () => {
    m.lists.mockResolvedValue([good, poison])
    m.tasks.mockImplementation(async (listId: string) => (listId === 'good'
      ? HEALTHY
      : [task({ uid: 'c', list: 'poison', summary: 'Charlie', href: '/poison/c.ics' })]))
    setup()

    await waitFor(() => expect(rows()).toEqual(['Alpha', 'Bravo', 'Charlie']))
  })
})

describe('2026-08-25 — the disk mirror on a cold boot', () => {
  /** Reads what the provider is actually holding, which is the only thing the
   *  finding is about — the paint happens off this array. */
  function Probe() {
    const { cals } = useCalendarData()
    return <div data-testid="cals">{cals.map((c) => c.name).join(',') || 'NONE'}</div>
  }

  // ── AUDIT (open): data.tsx:775 — the calendar's disk mirror is wiped on every
  //    cold boot; the logout-clear effect also fires on mount while auth is
  //    still 'loading' ───────────────────────────────────────────────────────
  it.fails('survives a mount that happens before /api/me has answered', async () => {
    // EVIDENCE. `CalendarProvider` seeds `cals` from `readCachedCalendars()` so
    // the first frame has content, then an effect clears everything whenever
    // `enabled` is false. `enabled` is `auth === 'in'` and `auth` starts at
    // `'loading'` (App.tsx:37), so the effect runs ON MOUNT, before `/api/me`
    // has answered, and `setCals([])` throws the seed away along with
    // `seeded.current` and `latest.current`. The effect was added to fix logout
    // leakage — the true->false TRANSITION — and does not distinguish that from
    // the initial false.
    //
    // The result is that the entire calendar half of cache.ts is dead code in
    // practice. On every cold load the Calendar tab mounts with zero calendars,
    // `requestWindow(from, to, [])` returns early because `!forCals.length`, and
    // the events request is serialised behind /api/me -> /api/calendars ->
    // /api/calendars/{id}/events. On a phone over a slow link that is a blank
    // month and an empty sidebar for two full round trips — precisely the
    // waterfall cache.ts's header says it exists to remove. `TaskProvider` has
    // no such effect, so lists and tasks DO paint from cache: the two halves of
    // one provider behave differently.
    //
    // The mirror is keyed on the account name and `write` NO-OPS without one,
    // which the shared `beforeEach` clears to keep every other suite cold. So
    // this pin has to name a user, and then PROVE the mirror took — an
    // un-warmed mirror reads 'NONE' for a reason that has nothing to do with the
    // finding, and would go on reading 'NONE' after the fix.
    setCacheUser('owner')
    cacheLists([{ ...good, name: 'Inbox' }])
    cacheCalendars([cal])
    expect(readCachedCalendars()?.map((c) => c.name),
      'the mirror was never written, so this pin would be vacuous')
      .toEqual(['Personal'])

    // This is exactly what App renders while `/api/me` is in flight.
    render(
      <DataProvider rev={0} onExpire={vi.fn()} enabled={false}>
        <Probe />
      </DataProvider>,
    )

    // The LISTS half of the same provider has no such effect and survives — the
    // two halves disagreeing is the finding.
    expect(screen.getByTestId('cals')).toHaveTextContent('Personal')
  })

  // CONTROL (passes today, must keep passing). A real logout — `enabled` going
  // true -> false — still clears the calendars. That is the leak the effect was
  // added for, and the cheap over-correction for the pin above is to delete the
  // effect.
  it('still clears the calendars when a signed-in session ends', async () => {
    setCacheUser('owner')
    cacheCalendars([cal])
    m.calendars.mockResolvedValue([cal])
    const Harness = ({ on }: { on: boolean }) => (
      <DataProvider rev={0} onExpire={vi.fn()} enabled={on}><Probe /></DataProvider>
    )
    const { rerender } = render(<Harness on />)
    await waitFor(() => expect(screen.getByTestId('cals')).toHaveTextContent('Personal'))

    rerender(<Harness on={false} />)
    expect(screen.getByTestId('cals')).toHaveTextContent('NONE')
  })
})

// ════════════════════════════════════════════════════════════════════════════
// App — boot
// ════════════════════════════════════════════════════════════════════════════

describe('2026-08-25 — booting with the server unreachable', () => {
  // ── AUDIT (open): App.tsx:160 — boot treats "can't reach the server" as
  //    "signed out": a network drop or a 502 on /api/me hands the owner a login
  //    card and hides their cached data ──────────────────────────────────────
  it.fails('does not hand the owner a sign-in card', async () => {
    // EVIDENCE. The boot handler is
    // `api.me().then(...).catch(() => setAuth('out'))`. `j()` produces
    // `AuthError` only for a 401 — a dropped connection rejects with a
    // `TypeError` and a 5xx with `HttpError` — and all three land in that one
    // catch, so ANY transport failure renders `<Login>`.
    //
    // That is the exact inversion of the rule the SSE loop in this same codebase
    // states and enforces: "A server that is down is not a session that is gone,
    // and signing a live session out on one 502 from the tunnel would be a worse
    // bug than the one this fixes" (api.ts:791). Setting `auth='out'` also flips
    // `enabled` false, which makes `CalendarProvider` clear its state, so the
    // last-known-good data the disk mirror was built to show is unreachable from
    // the login card.
    //
    // Scenario: the owner opens the PWA on a flaky connection.
    // `fetch('/api/me')` rejects. They get the sign-in card, type their
    // password, `POST /api/login` also fails, and the card shows a raw transport
    // message — while their session cookie is still perfectly valid and their
    // tasks are sitting in localStorage.
    //
    // NOTE FOR WHOEVER FIXES THIS: `App.test.tsx:56` pins the CURRENT behaviour
    // with `m.me.mockRejectedValue(new Error('unauthenticated'))` — a bare
    // Error, which is neither an `AuthError` nor a 401 — so that test cannot
    // tell the two cases apart either and will need re-pointing at a real
    // `AuthError`.
    //
    // ASSERTED AS THE OUTCOME: a transport failure is not a sign-out. A third
    // state, a retry, a banner over the cached shell — any of them satisfies it.
    // The pin does not require particular copy.
    m.me.mockRejectedValue(new HttpError(502, 'bad gateway'))
    render(<App />)

    // Something has to settle before the absence means anything: the login card
    // is what renders on the failure path today, so wait for the boot to finish
    // by waiting for `me` to have been called and the shell to stop being busy.
    await waitFor(() => expect(m.me).toHaveBeenCalled())
    await waitFor(() => expect(document.querySelector('[aria-busy="true"]')).toBeNull())

    expect(screen.queryByLabelText('Password'),
      'a 502 from the tunnel rendered the sign-in card').not.toBeInTheDocument()
  })

  // CONTROL (passes today, must keep passing). A real 401 still signs out. The
  // cheap over-correction for the pin above is to stop signing out on any
  // failure, which would leave a genuinely lapsed session staring at an empty
  // shell with no way to log back in.
  it('still shows the sign-in card when the session really has lapsed', async () => {
    m.me.mockRejectedValue(new AuthError('unauthenticated'))
    render(<App />)

    expect(await screen.findByLabelText('Password')).toBeInTheDocument()
  })
})

// ════════════════════════════════════════════════════════════════════════════
// TodayView
// ════════════════════════════════════════════════════════════════════════════

describe('2026-08-25 — the Today tab', () => {
  const setup = () => {
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TodayView rev={0} onExpire={vi.fn()} />
      </DataProvider>,
    )
    return userEvent.setup()
  }

  const dayRows = () =>
    [...document.querySelectorAll('.today-row:not(.today-sug):not(.today-habit)')]
  const rowFor = (title: string) =>
    dayRows().find((r) => r.querySelector('.today-title')?.textContent?.includes(title))!

  /** The exact event sequence a browser emits for a row drag, at the targets it
   *  uses. `mousedown` lands on the deepest node and `dragstart` at the drag
   *  SOURCE, which is what TodayView's own guard is written against. */
  const hoverDuringDrag = (from: string, over: string) => {
    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }
    fireEvent.mouseDown(rowFor(from).querySelector('.today-title')!)
    fireEvent.dragStart(rowFor(from), { dataTransfer })
    fireEvent.dragOver(rowFor(over), { dataTransfer })
    return rowFor(over).outerHTML
  }

  const THREE = [
    dayEntry({ entry_id: 'a', title: 'Alpha', position: 1 }),
    dayEntry({ entry_id: 'b', title: 'Bravo', position: 2 }),
    dayEntry({ entry_id: 'c', title: 'Charlie', position: 3 }),
  ]

  // ── AUDIT (open): TodayView.tsx:1761 — the drop indicator draws above the
  //    target on a downward drag, but the row lands below it ────────────────
  it.fails('points at the gap the row will actually land in', async () => {
    // EVIDENCE. `dragOver` is a single BOOLEAN —
    // `dragOver={overId === e.entry_id && dragId !== null && dragId !== e.entry_id}`
    // — and `.today-row.drag-over { box-shadow: inset 0 2px 0 var(--accent) }`
    // paints the accent rule on the row's TOP edge unconditionally, while
    // `moveRow` deliberately lands a downward drag AFTER the target ("Dragging
    // DOWN lands the row AFTER the target"). So during every downward drag the
    // line the owner is aiming at is one gap above where the row will go.
    //
    // This is the exact defect the Tasks pane already fixed, with `drag.below`
    // and `.task-drag.drag-over.drag-below > .task { box-shadow: inset 0 -2px 0 }`
    // (TasksView.tsx:149, app.css:307). The Today tab's drag is a separate,
    // newer code path that never got it.
    //
    // Measured in this harness with Alpha(1)/Bravo(2)/Charlie(3):
    //   DOWN (Alpha onto Bravo) hovered class "today-row today-draggable drag-over"
    //        write position 2.5 -> Bravo, Alpha, Charlie
    //   UP   (Charlie onto Bravo) hovered class "today-row today-draggable drag-over"
    //        write position 1.5 -> Alpha, Charlie, Bravo
    // Identical indicator, opposite outcomes; only the upward reading matches.
    //
    // ASSERTED AS "THESE TWO MUST DIFFER", deliberately. Both drags hover the
    // SAME row, so its rendering is the only variable, and any honest fix — a
    // direction class, a data attribute, an inline box-shadow, an inserted
    // indicator node — changes it. Naming `today-below` here would pin the one
    // repair the suggested fix happens to lead with.
    m.openDay.mockResolvedValue(plan(THREE))
    setup()
    await screen.findByText('Alpha')

    const down = hoverDuringDrag('Alpha', 'Bravo')
    fireEvent.dragEnd(rowFor('Alpha'))
    const up = hoverDuringDrag('Charlie', 'Bravo')

    expect(down, 'the drop indicator renders identically for an upward and a '
      + 'downward drag, but the row lands on opposite sides of the target')
      .not.toBe(up)
  })

  // ── AUDIT (open): TodayView.tsx:646 — a failed day read leaves the Today tab
  //    blank with no error, no empty state and no retry, and every add then
  //    paints nothing ────────────────────────────────────────────────────────
  it.fails('says the day could not be read, and does not swallow the next add', async () => {
    // EVIDENCE. `plan` only ever becomes non-null on a successful 200
    // (`if (p && Array.isArray(p.entries)) setPlan(p)` — nothing on the failure
    // arm); a rejection is swallowed by `guard` into a transient toast.
    // `allEntries`/`entries` therefore stay `null` forever, and every render of
    // the day is gated on `entries !== null` — INCLUDING the empty state — so
    // the tab shows its heading, add box, calendar strip and suggestions over a
    // blank space that says nothing, with no retry short of navigating away and
    // back.
    //
    // `POST /api/day/{day}/open` is the expensive call on this screen (it
    // derives a snapshot from CalDAV), so a Radicale hiccup that times out that
    // one call while every other endpoint is healthy is the realistic trigger.
    // In that state every optimistic writer is a no-op, because they all read
    // `setPlan((p) => (p && … : p))`: the owner types a line, presses Add, the
    // POST SUCCEEDS server-side, the box clears — and no row appears.
    //
    // Measured with `m.openDay.mockRejectedValue(new Error('boom'))`:
    //   .empty -> [ 'Nothing on the calendar today.' ]   (nothing about the day)
    //   then type "call the bank", Add -> api.addDayEntry IS called, the input
    //   clears, and .today-row -> []
    //
    // ASSERTED IN TWO HALVES, both structural rather than lexical. (a) The day
    // has SOMETHING to say that is not the calendar strip's own empty line — an
    // error line, a retry, any empty/alert/banner of its own; the pin does not
    // name the copy. (b) A write cannot land invisibly: either the add is
    // refused, or the row it created is on screen.
    m.openDay.mockRejectedValue(new Error('boom'))
    const user = setup()
    const box = await screen.findByLabelText('Add to today')
    await waitFor(() => expect(m.openDay).toHaveBeenCalled())

    const said = [...document.querySelectorAll('.empty, .banner, [role="alert"], [role="status"]')]
      .map((n) => n.textContent?.trim())
      .filter((t) => t && t !== 'Nothing on the calendar today.')

    await user.type(box, 'call the bank{Enter}')
    await waitFor(() => expect(box).toHaveValue(''))
    const landed = m.addDayEntry.mock.calls.length > 0
    const visible = [...document.querySelectorAll('.today-row')]
      .some((r) => r.textContent?.includes('call the bank'))

    // BOTH halves in one assertion, deliberately. Asserted in sequence, the
    // second never runs while the first is red, and a fix to only one of them
    // would then read as complete.
    expect({ surfaced: said.length > 0, wroteInvisibly: landed && !visible },
      `the day failed to read: the tab said ${JSON.stringify(said)}, and the `
      + `note ${landed ? 'reached the server' : 'was refused'} and is `
      + `${visible ? 'on screen' : 'nowhere'}`)
      .toEqual({ surfaced: true, wroteInvisibly: false })
  })

  // CONTROL (passes today, must keep passing). A day that reads successfully but
  // holds nothing still says so, and an add still paints. The over-correction
  // for the pin above is to gate the add box on a flag that is never cleared.
  it('still shows the empty state and still paints an add on a healthy day', async () => {
    const user = setup()
    const box = await screen.findByLabelText('Add to today')
    expect(await screen.findByText(/Nothing on today yet/)).toBeInTheDocument()

    await user.type(box, 'call the bank{Enter}')
    await waitFor(() => expect(
      [...document.querySelectorAll('.today-row')]
        .some((r) => r.textContent?.includes('call the bank'))).toBe(true))
  })
})

describe('2026-08-25 — the shutdown ritual, step two', () => {
  const setup = () => {
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TodayView rev={0} onExpire={vi.fn()} />
      </DataProvider>,
    )
    return userEvent.setup()
  }

  const openCarry = async (user: ReturnType<typeof setup>) => {
    await user.click(await screen.findByRole('button', { name: 'Shut down' }))
    const dialog = await screen.findByRole('dialog', { name: 'Shut down the day' })
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    return dialog
  }

  const DONE_SENTENCE = 'Everything on today is done. Nothing to carry.'

  // ── AUDIT (open): ShutdownRitual.tsx:232 — step 2 reports "Everything on
  //    today is done" after the owner MOVED everything to tomorrow ──────────
  it.fails('does not call a day that was postponed a day that was finished', async () => {
    // EVIDENCE. `unfinished = entries.filter((e) => !isDone(e))`, and
    // `TodayView.entries` filters out rows carrying `rolled_to` as well as
    // `dropped_at` — by design, so a decided row leaves the day's total. The
    // consequence is that the "Move all N to tomorrow" sweep, or dropping the
    // last leftover, empties `unfinished` and the step falls through to an
    // empty state that states the opposite of what happened: nothing was done,
    // everything was postponed. On the one screen whose whole job is an honest
    // record of the day, that is a lie the owner has just personally disproved.
    //
    // Reproduced: a day holding two undone rows; Shut down -> Next -> "Move all
    // 2 to tomorrow"; `rollDayEntry` called twice, then `.plan-body` reads
    // "Everything on today is done. Nothing to carry."
    //
    // ASSERTED AS THE EXACT FALSE SENTENCE, which is the one thing every correct
    // repair removes from this path. The suggested fix words it "Everything on
    // today is decided."; a count, a different empty state, or keeping the rolled
    // rows listed would each satisfy this too. The control below is what stops a
    // "fix" that simply deletes the sentence.
    m.openDay.mockResolvedValue(plan([
      dayEntry({ entry_id: 'a', title: 'Alpha', position: 1 }),
      dayEntry({ entry_id: 'b', title: 'Bravo', position: 2 }),
    ]))
    const user = setup()
    const dialog = await openCarry(user)

    await user.click(within(dialog).getByRole('button', { name: /Move all 2 to tomorrow/ }))
    await waitFor(() => expect(m.rollDayEntry).toHaveBeenCalledTimes(2))

    expect(dialog.querySelector('.plan-body')?.textContent?.trim(),
      'the owner moved every row to tomorrow and was told they were done')
      .not.toBe(DONE_SENTENCE)
  })

  // CONTROL (passes today, must keep passing). A day whose rows really were
  // ticked still gets the sentence. Deleting it, or replacing it everywhere with
  // "decided", would satisfy the pin above and lose the one thing this step is
  // for saying.
  it('still says everything is done when everything was done', async () => {
    m.openDay.mockResolvedValue(plan([
      dayEntry({ entry_id: 'a', title: 'Alpha', position: 1, done_at: '2026-08-21T17:00:00.000Z' }),
    ]))
    const user = setup()
    const dialog = await openCarry(user)

    expect(dialog.querySelector('.plan-body')?.textContent?.trim()).toBe(DONE_SENTENCE)
  })
})

// ════════════════════════════════════════════════════════════════════════════
// BookingPage — the public, anonymous surface
// ════════════════════════════════════════════════════════════════════════════

describe('2026-08-25 — the booking page after a taken slot', () => {
  const INFO: PublicBookingInfo = {
    token: 'tok', title: 'Intro call', description: 'Say hi', duration_minutes: 30,
    timezone: 'UTC',
    // Mid-day UTC keeps the local-day grouping stable in any test zone.
    slots: [
      { start: '2026-07-20T10:00:00+00:00', end: '2026-07-20T10:30:00+00:00' },
      { start: '2026-07-20T11:00:00+00:00', end: '2026-07-20T11:30:00+00:00' },
    ],
  }

  // ── AUDIT (open): BookingPage.tsx:265 — "That time was just taken" stays on
  //    screen after the visitor does what it told them to do ────────────────
  it.fails('clears the warning once the visitor picks another slot', async () => {
    // EVIDENCE. The 409 recovery path sets `error`, clears the slot and returns
    // to `pick`. Nothing clears `error` when a NEW slot is chosen — the slot
    // button's handler is `() => { setSlot(s); setCid(clientId()); setPhase(…) }`
    // — so the warn-bordered `role="alert"` banner "That time was just taken —
    // please pick another." is still rendered above the confirm bar for the new
    // slot, and stays there while the visitor types their name and email and
    // presses Confirm. It only disappears if the second booking also fails
    // (replaced) or succeeds (the `done` branch renders instead).
    //
    // An anonymous visitor is being told their currently-selected slot is gone
    // at the exact moment they are asked to confirm it. This is the app's one
    // unauthenticated surface, where there is nobody to explain it to them.
    //
    // Reproduced: `publicBook` rejects with `HttpError(409, …)`; book slot 1,
    // see "just taken", click slot 2 -> `.booking-picked` is present (confirm
    // phase) AND `.booking-err` still reads the warning.
    m.publicBookingInfo.mockResolvedValue(INFO)
    m.publicBook.mockRejectedValue(new HttpError(409, 'that time is not available'))
    const user = userEvent.setup()
    render(<BookingPage token="tok" />)
    await screen.findByText('Intro call')

    await user.click(document.querySelectorAll('.slot-btn')[0] as HTMLElement)
    await user.type(screen.getAllByRole('textbox')[0], 'Ada')
    await user.type(document.querySelector('input[type="email"]') as HTMLElement, 'ada@example.com')
    await user.click(screen.getByRole('button', { name: /confirm booking/i }))
    await screen.findByText(/just taken/i)

    await user.click(document.querySelectorAll('.slot-btn')[1] as HTMLElement)

    expect(document.querySelector('.booking-picked'),
      'the harness never reached the confirm bar for the second slot').not.toBeNull()
    expect(screen.queryByText(/just taken/i),
      'the visitor did exactly what the alert asked and it is still there, over '
      + 'the slot they have just chosen').not.toBeInTheDocument()
  })

  // CONTROL (passes today, must keep passing). The warning IS shown when the
  // slot is taken. The cheap over-correction for the pin above is to clear
  // `error` somewhere that also clears it before the visitor can read it.
  it('still tells the visitor when their slot was taken', async () => {
    m.publicBookingInfo.mockResolvedValue(INFO)
    m.publicBook.mockRejectedValue(new HttpError(409, 'that time is not available'))
    const user = userEvent.setup()
    render(<BookingPage token="tok" />)
    await screen.findByText('Intro call')

    await user.click(document.querySelectorAll('.slot-btn')[0] as HTMLElement)
    await user.type(screen.getAllByRole('textbox')[0], 'Ada')
    await user.type(document.querySelector('input[type="email"]') as HTMLElement, 'ada@example.com')
    await user.click(screen.getByRole('button', { name: /confirm booking/i }))

    expect(await screen.findByText(/just taken/i)).toBeInTheDocument()
  })
})

// ════════════════════════════════════════════════════════════════════════════
// HomeView — the dashboard board
// ════════════════════════════════════════════════════════════════════════════

describe('2026-08-25 — clearing the dashboard', () => {
  const labels = () =>
    [...document.querySelectorAll('.dash-mod-head > .label')].map((n) => n.textContent)

  /** Controlled the way App holds it — the finding is entirely about what
   *  happens on the render AFTER the change is fed back, so a harness that
   *  dropped the write would not see it. */
  function Board({ initial }: { initial: DashboardModule[] }) {
    const [layout, setLayout] = useState(initial)
    return (
      <DataProvider rev={0} onExpire={vi.fn()}>
        <HomeView rev={0} onExpire={vi.fn()} layout={layout} onLayoutChange={setLayout} />
      </DataProvider>
    )
  }

  // ── AUDIT (open): HomeView.tsx:52 — removing the last Home module puts the
  //    five stock modules back on the board ─────────────────────────────────
  it.fails('does not put five modules back when the last one is removed', async () => {
    // EVIDENCE. `const committed = layout.length ? layout : DEFAULT_LAYOUT`
    // treats an empty saved layout as "never arranged". `removeModule` on the
    // final module produces `[]`, `commit` passes that to `onLayoutChange`, App
    // persists `dashboard: []`, and the component immediately re-renders with
    // all five default modules — Today, Upcoming, Mini calendar, Overdue,
    // Recently completed.
    //
    // So pressing Remove ADDS five modules, including a mini calendar that
    // starts fetching a six-week window of events the user has just removed. It
    // also makes an empty (or nearly empty) dashboard unrepresentable, and it is
    // not reversible from the UI: the state survives a reload, because `[]` is
    // what was stored. A user clearing the board to start fresh gets the whole
    // stock arrangement back on the last removal, and "Add module" then offers
    // only the three kinds that are left.
    //
    // ASSERTED IN BOTH BRANCHES, because both are correct answers and neither
    // may be silent: either Remove is refused on the last module (the board
    // still holds exactly that one), or it is honoured and the board is empty.
    // What is not correct is the third thing.
    const user = userEvent.setup()
    render(<Board initial={[{ id: 'a', kind: 'quick_add', x: 0, y: 0, w: 4, h: 3 }]} />)
    await user.click(await screen.findByRole('button', { name: 'Arrange' }))

    const remove = screen.getByRole('button', { name: 'Remove Quick add' })
    if ((remove as HTMLButtonElement).disabled) {
      expect(labels(), 'Remove is disabled, so the board must be untouched')
        .toEqual(['Quick add'])
    } else {
      await user.click(remove)
      expect(labels(), 'removing the last module put the stock arrangement back')
        .toEqual([])
    }
  })

  // CONTROL (passes today, must keep passing). Removing one of several still
  // removes exactly that one. The over-correction for the pin above is to
  // disable Remove more widely than the last module.
  it('still removes a module when others remain', async () => {
    const user = userEvent.setup()
    render(<Board initial={[
      { id: 'a', kind: 'quick_add', x: 0, y: 0, w: 4, h: 3 },
      { id: 'b', kind: 'today', x: 4, y: 0, w: 4, h: 6 },
    ]} />)
    await user.click(await screen.findByRole('button', { name: 'Arrange' }))

    await user.click(screen.getByRole('button', { name: 'Remove Quick add' }))
    expect(labels()).toEqual(['Today'])
  })
})

// ════════════════════════════════════════════════════════════════════════════
// CalendarView — the month grid
// ════════════════════════════════════════════════════════════════════════════

describe('2026-08-25 — reaching the month grid from a keyboard', () => {
  const FOCUSABLE = 'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])'

  function CalHarness() {
    const now = new Date()
    const [cursor, setCursor] = useState(() => new Date(now.getFullYear(), now.getMonth(), 1))
    const [shown, setShown] = useState<string[]>([])
    return (
      <DataProvider rev={0} onExpire={vi.fn()}>
        <CalendarView onExpire={vi.fn()} cursor={cursor} onCursorChange={setCursor}
          sideCollapsed={false} onToggleSide={vi.fn()}
          hiddenCalendars={[]} onHiddenCalendarsChange={vi.fn()}
          archivedCalendars={[]} onArchivedCalendarsChange={vi.fn()}
          calTaskLists={shown} onCalTaskListsChange={setShown}
          calShowDone={false} onCalShowDoneChange={vi.fn()} fit="dynamic" />
      </DataProvider>
    )
  }

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date(2026, 2, 5))
    m.calendars.mockResolvedValue([cal])
    m.events.mockResolvedValue([ev()])
  })
  afterEach(() => { vi.useRealTimers() })

  /** Whether a node can be reached AND activated from a keyboard: a real
   *  control, or an element carrying both a button-ish role and a tab stop. */
  const operable = (el: Element | null) => {
    if (!el) return false
    if (el.tagName === 'BUTTON' || (el.tagName === 'A' && el.hasAttribute('href'))) return true
    const tabindex = el.getAttribute('tabindex')
    return !!el.getAttribute('role') && tabindex !== null && Number(tabindex) >= 0
  }

  const describeNode = (el: Element | null) => el
    ? `${el.tagName} role=${el.getAttribute('role')} tabindex=${el.getAttribute('tabindex')}`
    : 'MISSING'

  // ── AUDIT (open): CalendarView.tsx:623 — the whole month grid is
  //    keyboard-inoperable: day cells and event chips are unfocusable divs ──
  it.fails('exposes the event chip and the day cell as operable controls', async () => {
    // EVIDENCE. Every interactive surface in the month grid is a plain
    // `<div onClick>` with no `role`, no `tabIndex` and no `onKeyDown`: the day
    // cell (line 584 — the only way to create an event on that day), the event
    // chip (line 636 — the only way to OPEN an event), and the task chip. Tabbing
    // from the header's Today button skips the entire grid.
    //
    // Measured against the real component, a March 2026 grid holding one event:
    //   focusable nodes inside .cal-grid: 0
    //   chip  tag/role/tabindex: DIV null null
    //   cell  tag/role/tabindex: DIV null null
    // (query: `a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])`)
    //
    // The same component gets this right elsewhere — `+N more` is a real
    // `<button>`, the mobile agenda rows are `<button>`s, and the sidebar's
    // task-list rows carry `role="checkbox" tabIndex={0}` with a Space/Enter
    // handler — so the omission is inconsistent within one file. A screen reader
    // also announces the chips as static text, with the recurrence marker and
    // the clock read as part of the label.
    //
    // ASSERTED AS OPERABILITY, not as a repair: a real `<button>`, or a
    // `role` plus a non-negative `tabindex`, both pass. A roving tabindex over
    // the 42 cells (the suggested fix for the grid) passes too, since at least
    // one cell carries `tabindex="0"` at any time. Deliberately NOT asserted by
    // pressing Enter: jsdom does not synthesise a click from Enter on a
    // `<button>`, so an Enter assertion would go RED against the most obvious
    // correct fix.
    render(<CalHarness />)
    const grid = await waitFor(() => {
      const g = document.querySelector('.cal-grid')
      expect(g?.querySelector('.cal-ev')).toBeTruthy()
      return g!
    })

    const chip = grid.querySelector('.cal-ev')
    const cell = grid.querySelector('.cal-cell')
    const reachable = grid.querySelectorAll(FOCUSABLE).length

    expect({
      chip: operable(chip), cell: operable(cell), reachable: reachable > 0,
    }, `nothing in the month grid can be reached from a keyboard — chip is `
      + `${describeNode(chip)}, cell is ${describeNode(cell)}, and the grid holds `
      + `${reachable} focusable nodes`)
      .toEqual({ chip: true, cell: true, reachable: true })
  })

  // CONTROL (passes today, must keep passing). The chip still OPENS the editor
  // on a click. The over-correction for the pin above is to swap the div for a
  // button and lose the handler, or to make the cell a button that swallows the
  // chip's own click.
  it('still opens an event when the chip is clicked', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<CalHarness />)
    await waitFor(() => expect(document.querySelector('.cal-ev')).toBeTruthy())

    await user.click(document.querySelector('.cal-ev') as HTMLElement)
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })
})
