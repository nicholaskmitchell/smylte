/**
 * The 2026-09-03 sweep, fe-tasks-calendar: the Calendar tab's event editor, the
 * Tasks tab's rows, and the sidebar the two share.
 *
 * Nine findings, one `it` each, every one written first against the unfixed
 * code and red for the reason its comment names. What they share is a surface
 * that had been given a fix once already and kept the OTHER half of the same
 * shape: the drag path learned `hasZone`/`instantFromLocal` and the modal did
 * not; the edit modal got the modal contract and the drawer beside it did not;
 * the month grid became keyboard-operable and the task rows it opens the same
 * editor from did not; Home rolls "today" over at midnight and the two tabs
 * that say "today" loudest do not.
 *
 * The suite runs pinned to America/New_York (vite.config.ts), which is what
 * makes the Berlin fixture below read as 03:30 on the pickers.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { useState } from 'react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { CalendarView } from './components/CalendarView'
import { TasksView } from './components/TasksView'
import { Sidebar } from './components/Sidebar'
import { TaskModal } from './components/TaskModal'
import { DataProvider } from './data'
import { I18nProvider } from './i18n'
import { setCacheUser } from './cache'
import { setBreakpoint } from './test/setup'
import { api, type CalEvent, type List, type Task } from './api'
import type { CalendarFit } from './calendar'

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
  completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
  created: null, last_modified: null,
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

const list = (id: string, name: string, color: string | null = null): List => ({
  id, href: `/${id}/`, name, is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color,
})

const cal: List = {
  id: 'c1', href: '/c1/', name: 'Work', is_task_list: false, is_calendar: true,
  open_count: 0, task_count: 0, event_count: 1, total: 1, color: '#D9480F',
}

const ev = (o: Partial<CalEvent> = {}): CalEvent => ({
  uid: 'u1', id: 'u1', recurrence_id: null, is_recurring: false, calendar: '/c1/',
  summary: 'Standup', description: null, location: null,
  start: '2026-08-10T09:00:00', start_is_date: false,
  end: '2026-08-10T09:30:00', end_is_date: false, duration: null,
  all_day: false, status: null, busy: true, notify_minutes_before: null, tags: [], has_rrule: false,
  href: '/c1/u1.ics', etag: '"1"', ...o,
})

const noopApi = {
  create: vi.fn(async () => undefined),
  update: vi.fn(async () => undefined),
  remove: vi.fn(async () => undefined),
  reorder: vi.fn(async () => undefined),
}

let errSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  vi.clearAllMocks()
  setCacheUser('')
  localStorage.clear()
  m.lists.mockResolvedValue([list('l1', 'Work', '#D9480F')])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([cal])
  m.events.mockResolvedValue([])
  m.patchEvent.mockResolvedValue(ev())
  m.patchTask.mockResolvedValue(task())
  errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  errSpy.mockRestore()
  vi.useRealTimers()
})

// ── harnesses ──────────────────────────────────────────────────────────────

/** CalendarView over a real provider, the month held here as App holds it. */
function CalHarness({ fit = 'dynamic' as CalendarFit }) {
  const now = new Date()
  const [cursor, setCursor] = useState(() => new Date(now.getFullYear(), now.getMonth(), 1))
  return (
    <DataProvider rev={0} onExpire={vi.fn()}>
      <CalendarView onExpire={vi.fn()} cursor={cursor} onCursorChange={setCursor}
        sideCollapsed={false} onToggleSide={vi.fn()}
        hiddenCalendars={[]} onHiddenCalendarsChange={vi.fn()}
        archivedCalendars={[]} onArchivedCalendarsChange={vi.fn()}
        calTaskLists={[]} onCalTaskListsChange={vi.fn()}
        calShowDone={false} onCalShowDoneChange={vi.fn()}
        fit={fit} />
    </DataProvider>
  )
}

function calSetup(events: CalEvent[]) {
  m.events.mockResolvedValue(events)
  render(<CalHarness />)
  return userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
}

async function openEvent(user: ReturnType<typeof userEvent.setup>, name = 'Standup') {
  await waitFor(() => expect(screen.getAllByTitle(new RegExp(`^${name}`))[0]).toBeInTheDocument())
  await user.click(screen.getAllByTitle(new RegExp(`^${name}`))[0])
  return screen.findByRole('dialog')
}

const patchBody = () => m.patchEvent.mock.calls[0][2] as Record<string, unknown>

/** userEvent types character-by-character, which a datetime-local input cannot
 *  accept; set those directly. */
const setField = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } })

/** TasksView over a real provider. */
function tasksSetup(view: 'list' | 'day3' = 'list') {
  render(
    <DataProvider rev={0} onExpire={vi.fn()}>
      <TasksView onExpire={vi.fn()} view={view} onView={vi.fn()}
        sideCollapsed={false} onToggleSide={vi.fn()}
        hiddenLists={[]} onHiddenListsChange={vi.fn()}
        groups={[]} onGroupsChange={vi.fn()}
        collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
        collapsedTasks={[]} onCollapsedTasksChange={vi.fn()}
        showCompleted={false} />
    </DataProvider>,
  )
}

/** A Sidebar whose `items` are STATE, fed back through `onItems` the way the
 *  provider's `setLists` is — so a rollback lands on whatever the array holds
 *  by then, not on the render that started the write. `expose` hands the
 *  setter out so a test can play a concurrent server refresh. */
function SidebarHost({ initial, api: sbApi, expose }: {
  initial: List[]
  api: typeof noopApi
  expose?: (set: (next: List[]) => void) => void
}) {
  const [items, setItems] = useState(initial)
  expose?.(setItems)
  return (
    <Sidebar kind="list" items={items} countOf={(l) => l.open_count}
      onItems={setItems} api={sbApi as never}
      hiddenIds={new Set()} onHiddenChange={() => {}} />
  )
}

const rowNames = () =>
  Array.from(document.querySelectorAll('.side-item .name')).map((n) => n.textContent)

const rowFor = (name: string) =>
  Array.from(document.querySelectorAll('.side-item'))
    .find((r) => r.textContent?.includes(name)) as HTMLElement

/** One deferred promise: the write hangs until the test says otherwise. */
function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => { resolve = res })
  return { promise, resolve }
}

// ════════════════════════════════════════════════════════════════════════════
// CalendarView.tsx:1114 — the event editor and a zone-anchored DTSTART/DTEND
// ════════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — the event editor over a zone-anchored event', () => {
  beforeEach(() => {
    // August 2026 on the grid, so the Berlin fixture renders on it.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date(2026, 7, 5))
  })

  // `DTSTART;TZID=Europe/Berlin:20260810T093000`, as the read path serves it.
  // Under the suite's New York clock the pickers show 03:30 and 04:30.
  const berlin = () => ev({
    start: '2026-08-10T09:30:00+02:00', end: '2026-08-10T10:30:00+02:00',
  })

  it('a rename never writes the event\'s times back as naive wall clock', async () => {
    // EVIDENCE. `startOut = startVal` is the picker's naive local string, and
    // `commit()` spreads `{ start, end }` on every non-'all' save. The backend
    // re-expresses an incoming value in the property's own zone only when the
    // incoming one is aware, so "2026-08-10T03:30" lands as a FLOATING
    // DTSTART:20260810T033000 — the TZID gone, and in Berlin's own terms the
    // 09:30 standup now at 03:30, from a rename.
    //
    // Either repair passes: leaving the times off a save that did not touch
    // them, or sending the instant. What may not appear is the viewer's wall
    // clock with no zone on it.
    const user = calSetup([berlin()])
    await openEvent(user)
    await user.clear(screen.getByLabelText('Title'))
    await user.type(screen.getByLabelText('Title'), 'Renamed')
    await user.click(screen.getByText('Save'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    const b = patchBody()
    expect(b).toMatchObject({ summary: 'Renamed' })
    const wire = JSON.stringify(b)
    expect(wire).not.toContain('2026-08-10T03:30')
    expect(wire).not.toContain('2026-08-10T04:30')
    for (const k of ['start', 'end'] as const) {
      if (typeof b[k] === 'string') expect(b[k]).toMatch(/(Z|[+-]\d{2}:\d{2})$/)
    }
  })

  it('a changed time on a zone-anchored event goes as the instant it names', async () => {
    // The other half: when the user DOES move it, the new time has to reach
    // the server as an instant so `_set_datelike` can put it back in the
    // property's zone — `dateOut` in TaskModal, and `shiftIso` on the drag
    // path, already do exactly this for DUE and for a dragged chip.
    const user = calSetup([berlin()])
    await openEvent(user)
    setField('Start', '2026-08-10T04:00')          // 03:30 → 04:00 New York
    await user.click(screen.getByText('Save'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(patchBody()).toMatchObject({
      start: new Date('2026-08-10T04:00').toISOString(),
      end: new Date('2026-08-10T05:00').toISOString(),
    })
  })

  it('CONTROL: a changed time on a floating event still goes as the naive local form', async () => {
    // The app's own writes are floating and must stay so: an instant here
    // would have the server anchor a property that never had a zone.
    const user = calSetup([ev()])
    await openEvent(user)
    setField('Start', '2026-08-10T10:00')
    await user.click(screen.getByText('Save'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(patchBody()).toMatchObject({ start: '2026-08-10T10:00', end: '2026-08-10T10:30' })
  })

  it('a rename leaves start and end off the wire entirely', async () => {
    // The stricter shape, and the one that protects the DURATION-only and
    // floating cases too: a save that never touched the pickers has no
    // business restating DTSTART/DTEND — invariant #2, and the same discipline
    // `tagFields` and `busyFields` keep one line above. The recurring 'all'
    // branch already gated on `timeChanged`; the other three did not.
    const user = calSetup([ev()])
    await openEvent(user)
    await user.clear(screen.getByLabelText('Title'))
    await user.type(screen.getByLabelText('Title'), 'Renamed')
    await user.click(screen.getByText('Save'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(patchBody()).toMatchObject({ summary: 'Renamed' })
    expect(patchBody()).not.toHaveProperty('start')
    expect(patchBody()).not.toHaveProperty('end')
  })
})

// ════════════════════════════════════════════════════════════════════════════
// Sidebar.tsx:733 — the add form and a swatch tapped before the name
// ════════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — the sidebar add form on a WebKit swatch tap', () => {
  const addApi = () => ({
    ...noopApi, create: vi.fn(async (name: string) => list('new', name)),
  })
  const mount = () => render(
    <Sidebar kind="calendar" items={[]} countOf={(l) => l.open_count}
      onItems={() => {}} api={addApi() as never}
      hiddenIds={new Set()} onHiddenChange={() => {}} />,
  )

  it('a swatch press does not take focus off the name field', async () => {
    // EVIDENCE. The empty-form dismissal is gated on
    // `e.currentTarget.contains(e.relatedTarget)`, which is what keeps the form
    // open while a colour is picked — in engines that focus a <button> on
    // click. WebKit (macOS and iOS Safari) does not: `isMouseFocusable()` is
    // false for form controls there, and `dispatchMouseEvent` blurs the focused
    // element on mousedown with NO relatedTarget, so the input's blur arrives
    // with `relatedTarget === null`, `contains(null)` is false, and `onCancel`
    // unmounts the form before the swatch's click ever runs.
    //
    // jsdom does not model either engine's focus-on-click, so this cannot be
    // pinned as "the form survives a null-relatedTarget blur" without also
    // asserting a repair that keeps the blur happening. It pins the mechanism
    // that stops the blur instead: the swatch's mousedown is cancelled, which
    // in every engine means focus stays where it was.
    mount()
    await userEvent.click(screen.getByTitle('New calendar'))
    const input = screen.getByPlaceholderText('Calendar')
    expect(document.activeElement).toBe(input)

    // `fireEvent` returns false when a handler called preventDefault.
    expect(fireEvent.mouseDown(screen.getByTitle('#1565C0'))).toBe(false)
    expect(fireEvent.mouseDown(screen.getByTitle('No color'))).toBe(false)
    expect(screen.getByPlaceholderText('Calendar')).toBeInTheDocument()

    // …and the pick still lands.
    await userEvent.click(screen.getByTitle('#1565C0'))
    expect(screen.getByTitle('#1565C0')).toHaveClass('on')
  })
})

// ════════════════════════════════════════════════════════════════════════════
// Sidebar.tsx:461 — the mobile management drawer and the modal contract
// ════════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — the mobile management drawer', () => {
  const mount = () => render(
    <Sidebar kind="list" items={[list('work', 'Work'), list('home', 'Home')]}
      countOf={(l) => l.open_count} onItems={() => {}} api={noopApi as never}
      hiddenIds={new Set()} onHiddenChange={() => {}}
      groups={[]} onGroupsChange={() => {}}
      collapsedGroups={[]} onCollapsedGroupsChange={() => {}} />,
  )
  const openDrawer = async () => {
    setBreakpoint(true)
    mount()
    await userEvent.click(screen.getByRole('button', { name: /Lists/ }))
    return screen.getByRole('dialog')
  }

  it('closes on Escape, like the edit modal beside it', async () => {
    // EVIDENCE. The closed finding at docs/AUDIT.md "The sidebar's list/calendar
    // edit modal is the last dialog with no Escape…" ends its fix with "Do the
    // same for the mobile `.drawer-overlay`". EditModal got `useEscape`; the
    // drawer, in the same file, never did. A narrow desktop window renders it
    // too, with a keyboard in front of it.
    const dialog = await openDrawer()
    expect(dialog).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('keeps a half-typed name when a drag that began in the field is released on the scrim', async () => {
    // A `click` whose mousedown was inside the sheet is dispatched at the
    // nearest common ancestor — the overlay — so the sheet's stopPropagation
    // never sees it, and `onClick={closeDrawer}` ran `setAdding(false)` over
    // the form. The onMouseDown/onClick pair every other scrim uses is the fix.
    const dialog = await openDrawer()
    await userEvent.click(within(dialog).getByRole('button', { name: 'New list' }))
    const input = screen.getByPlaceholderText('List')
    await userEvent.type(input, 'Gro')
    const scrim = dialog.parentElement!

    fireEvent.mouseDown(input)
    fireEvent.click(scrim)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('List')).toHaveValue('Gro')

    // A genuine press-and-release on the scrim still closes it.
    fireEvent.mouseDown(scrim)
    fireEvent.click(scrim)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('declares itself modal, and its scrim keeps the press/release pair in source', async () => {
    // The half of modal-contract.test.tsx the drawer is invisible to: its four
    // rules match `className="overlay"` exactly and `overlay drawer-overlay`
    // does not. Asked here, of the one scrim that regex skips, in the same
    // terms that test uses.
    const dialog = await openDrawer()
    expect(dialog).toHaveAttribute('aria-modal', 'true')

    const src = readFileSync(resolve(__dirname, 'components/Sidebar.tsx'), 'utf8')
    const at = src.indexOf('className="overlay drawer-overlay"')
    expect(at).toBeGreaterThan(0)
    const after = src.slice(at, at + 240)
    const down = after.indexOf('onMouseDown=')
    const up = after.indexOf('onClick=')
    expect(down, 'the drawer scrim has no onMouseDown').toBeGreaterThanOrEqual(0)
    expect(down).toBeLessThan(up)
  })
})

// ════════════════════════════════════════════════════════════════════════════
// TasksView.tsx:1004 — rows a keyboard can open
// ════════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — opening a task from the keyboard', () => {
  it('a list row\'s body is focusable and Enter opens the editor', async () => {
    // EVIDENCE. `.task-body` is a div with `onClick` and nothing else. Tabbing
    // through a row reaches the twisty, the checkbox, "+ sub" and "✕" — every
    // control but the one that opens the task. The same task on the Calendar
    // tab is a `role="button"` chip with Enter/Space, and in DayPopover a real
    // <button>; the Tasks tab is the inconsistent surface, and for an undated
    // task it is the ONLY surface.
    m.tasks.mockResolvedValue([task()])
    tasksSetup('list')
    await screen.findByText('Ship it')
    const body = document.querySelector('.task-body') as HTMLElement
    body.focus()
    expect(document.activeElement).toBe(body)
    fireEvent.keyDown(body, { key: 'Enter' })
    expect(await screen.findByRole('dialog', { name: 'Task' })).toBeInTheDocument()
  })

  it('a day-column card\'s body is focusable and Space opens the editor', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-08-10T12:00:00-04:00'))
    m.tasks.mockResolvedValue([task({ due: '2026-08-10', due_is_date: true })])
    tasksSetup('day3')
    await screen.findByText('Ship it')
    const body = document.querySelector('.day-card-body') as HTMLElement
    body.focus()
    expect(document.activeElement).toBe(body)
    fireEvent.keyDown(body, { key: ' ' })
    expect(await screen.findByRole('dialog', { name: 'Task' })).toBeInTheDocument()
  })
})

// ════════════════════════════════════════════════════════════════════════════
// AddMultipleModal.tsx:191 — the priority picker's option text
// ════════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — the priority picker under German', () => {
  const modal = (lang: 'en' | 'de') => (
    <I18nProvider value={lang}>
      <TaskModal task={task()} lists={[list('l1', 'Work')]} defaultList="l1"
        onClose={() => {}} onCreate={() => {}} onSave={() => {}}
        onDelete={() => {}} onMultiple={() => {}} />
    </I18nProvider>
  )
  const optionTexts = (label: string) =>
    Array.from((screen.getByLabelText(label) as HTMLSelectElement).options).map((o) => o.text)

  it('shows translated choices, not the wire vocabulary', () => {
    // EVIDENCE. `{PRIORITIES.map((p) => <option value={p}>{p}</option>)}` puts
    // api.ts's wire strings on screen. The label beside it says "Priorität";
    // the four choices under it said none / low / medium / high. The German
    // guard test only sweeps for unresolved KEYS, so English words pass it.
    // Every other fixed-vocabulary select in the app translates its options
    // (the repeat picker, Show as, the reminder field).
    const { unmount } = render(modal('de'))
    const de = optionTexts('Priorität')
    expect(de).toHaveLength(4)
    for (const text of de) expect(text).not.toMatch(/^(none|low|medium|high)$/)
    unmount()

    // …and the English rendering is a different set of words, so the
    // catalogue — not a capitalised copy of the wire value — is what reached
    // the DOM. The VALUES stay the wire vocabulary in both.
    render(modal('en'))
    const en = optionTexts('Priority')
    expect(en).not.toEqual(de)
    const values = Array.from((screen.getByLabelText('Priority') as HTMLSelectElement).options)
      .map((o) => o.value)
    expect(values).toEqual(['none', 'low', 'medium', 'high'])
  })
})

// ════════════════════════════════════════════════════════════════════════════
// TasksView.tsx:445 / CalendarView.tsx:617 — "today" across midnight
// ════════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — a tab left open across midnight', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date(2026, 8, 4, 23, 55))       // Fri 2026-09-04, 23:55 local
  })
  const crossMidnight = async () => {
    await act(async () => { vi.advanceTimersByTime(20 * 60_000) })
  }

  it('the Tasks tab\'s today column moves to the new day', async () => {
    // EVIDENCE. `const todayKey = ymd(new Date())` is read once per render and
    // nothing re-renders the view at midnight — the provider changes only on an
    // SSE rev bump, which an idle account never produces. hooks.ts's `useToday`
    // exists for exactly "a surface that says today and is left open", and
    // HomeView and FocusView use it; these two tabs did not.
    tasksSetup('day3')
    await waitFor(() => expect(document.querySelector('.day-col.today')).not.toBeNull())
    expect(document.querySelector('.day-col.today .dnum')?.textContent).toBe('4')

    await crossMidnight()
    expect(document.querySelector('.day-col.today .dnum')?.textContent).toBe('5')
  })

  it('the Calendar tab\'s today cell moves to the new day', async () => {
    render(<CalHarness />)
    await waitFor(() => expect(document.querySelector('.cal-cell.today')).not.toBeNull())
    expect(document.querySelector('.cal-cell.today')?.getAttribute('data-day')).toBe('2026-09-04')

    await crossMidnight()
    expect(document.querySelector('.cal-cell.today')?.getAttribute('data-day')).toBe('2026-09-05')
  })
})

// ════════════════════════════════════════════════════════════════════════════
// Sidebar.tsx:220 — a failed drag-reorder
// ════════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — a sidebar reorder the server refused', () => {
  const dragTo = (from: string, onto: string) => {
    fireEvent.dragStart(rowFor(from), { dataTransfer: { effectAllowed: '' } })
    fireEvent.dragOver(rowFor(onto))
    fireEvent.drop(rowFor(onto))
  }

  it('puts the rows back in the order the server still holds', async () => {
    // EVIDENCE. `drop()` paints `onItems(next)` and discards the `api.reorder`
    // promise. The guard toasts on failure and returns undefined, nothing
    // reads it, and "server confirms via SSE" holds only on success — a failed
    // PROPPATCH publishes nothing, so no rev bump ever refetches. Rename,
    // recolor and delete in the same file all roll back; this was the one
    // write that did not.
    const sbApi = { ...noopApi, reorder: vi.fn(async () => undefined) }
    render(<SidebarHost initial={[list('a', 'Alpha'), list('b', 'Bravo'), list('c', 'Charlie')]}
      api={sbApi} />)
    dragTo('Charlie', 'Alpha')
    expect(sbApi.reorder).toHaveBeenCalledWith(['c', 'a', 'b'])
    await waitFor(() => expect(rowNames()).toEqual(['Alpha', 'Bravo', 'Charlie']))
  })

  it('CONTROL: restores positions by id, keeping a change that landed while it was in flight', async () => {
    // Only the POSITIONS come back, not a snapshot of the array: a rename that
    // arrived from the server mid-flight survives the rollback. data.tsx's task
    // reorder is the precedent ("Only the positions are remembered").
    //
    // A control, not a pin: it passed BEFORE the fix too, because with no
    // rollback at all the interleaved refresh is simply what stays on screen.
    // What it refuses is the obvious over-correction — `onItems(prev)` with a
    // whole-array snapshot, which would have painted "Bravo" back over the
    // rename. The pin for the finding itself is the case above.
    const d = deferred<undefined>()
    const sbApi = { ...noopApi, reorder: vi.fn(() => d.promise) }
    let set!: (next: List[]) => void
    render(<SidebarHost initial={[list('a', 'Alpha'), list('b', 'Bravo'), list('c', 'Charlie')]}
      api={sbApi} expose={(s) => { set = s }} />)
    dragTo('Charlie', 'Alpha')
    expect(rowNames()).toEqual(['Charlie', 'Alpha', 'Bravo'])
    // An SSE-driven refresh lands while the PROPPATCH is out: Bravo was renamed
    // elsewhere, and the server's order is still the old one.
    act(() => set([list('a', 'Alpha'), list('b', 'Bravo!'), list('c', 'Charlie')]))
    await act(async () => { d.resolve(undefined); await d.promise })
    expect(rowNames()).toEqual(['Alpha', 'Bravo!', 'Charlie'])
  })
})

// ════════════════════════════════════════════════════════════════════════════
// Sidebar.tsx:185 — rename/delete rollback over a concurrent refresh
// ════════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — a sidebar rename or delete that fails mid-refresh', () => {
  it('a failed rename restores only the renamed row', async () => {
    // EVIDENCE. `save()` captures `const prev = items` and calls `onItems(prev)`
    // on failure — a whole-array snapshot, so a list deleted by another client
    // while the PROPPATCH was out is resurrected, `loadKey` changes, the task
    // fan-out re-runs for it and 404s into the "Couldn't load" banner. Booking
    // links (SchedulingView) and the task reorder (data.tsx) closed this same
    // shape; the sidebar kept it.
    const d = deferred<List | undefined>()
    const sbApi = { ...noopApi, update: vi.fn(() => d.promise) }
    let set!: (next: List[]) => void
    render(<SidebarHost initial={[list('w', 'Work'), list('e', 'Errands'), list('o', 'Old')]}
      api={sbApi} expose={(s) => { set = s }} />)

    await userEvent.click(screen.getByRole('button', { name: 'Edit Errands' }))
    const field = screen.getByDisplayValue('Errands')
    await userEvent.clear(field)
    await userEvent.type(field, 'Chores')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(rowNames()).toEqual(['Work', 'Chores', 'Old'])

    // Old is deleted elsewhere; the SSE refetch replaces the array without it.
    act(() => set([list('w', 'Work'), list('e', 'Chores')]))
    await act(async () => { d.resolve(undefined); await d.promise })
    expect(rowNames()).toEqual(['Work', 'Errands'])
  })

  it('a failed delete re-inserts only the deleted row, where it was', async () => {
    const d = deferred<unknown>()
    const sbApi = { ...noopApi, remove: vi.fn(() => d.promise) }
    let set!: (next: List[]) => void
    render(<SidebarHost initial={[list('w', 'Work'), list('h', 'Home'), list('o', 'Old')]}
      api={sbApi} expose={(s) => { set = s }} />)

    await userEvent.click(screen.getByRole('button', { name: 'Edit Home' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await userEvent.click(screen.getByRole('button', { name: /Really delete/ }))
    expect(rowNames()).toEqual(['Work', 'Old'])

    act(() => set([list('w', 'Work'), list('n', 'New')]))    // Old gone, New arrived
    await act(async () => { d.resolve(undefined); await d.promise })
    expect(rowNames()).toEqual(['Work', 'Home', 'New'])
  })
})

// ════════════════════════════════════════════════════════════════════════════
// Sidebar.tsx:301 — a row lighting up for a drag that is not its own
// ════════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — a foreign drag over a sidebar row', () => {
  it('does not offer the row as a drop target', () => {
    // EVIDENCE. `renderRow`'s onDragOver calls `preventDefault()` and
    // `setOverId` unconditionally, and the class test `overId === l.id &&
    // dragId !== l.id` is true when `dragId` is null — so a task row dragged
    // from the list view, or a file from the desktop, paints the accent
    // insert line on every list it crosses, and `drop()` then returns early.
    // The group and ungrouped zones two screens down gate on `if (dragId)`.
    render(<SidebarHost initial={[list('a', 'Alpha'), list('b', 'Bravo')]} api={noopApi} />)
    const row = rowFor('Alpha')
    // No dragStart anywhere: this drag is somebody else's.
    expect(fireEvent.dragOver(row)).toBe(true)          // not defaultPrevented
    expect(row).not.toHaveClass('drag-over')

    // CONTROL: a sidebar drag of its own still lights the row.
    fireEvent.dragStart(rowFor('Bravo'), { dataTransfer: { effectAllowed: '' } })
    expect(fireEvent.dragOver(row)).toBe(false)
    expect(row).toHaveClass('drag-over')
  })
})
