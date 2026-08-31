/* CalendarView's component-level behaviour: what it actually sends to the API.
 *
 * The date arithmetic lives in calendar.ts and is covered table-driven there
 * (`dragBody`, `daysBetween`, `shiftIso`, `lastDayOf`). What is left here is the
 * part that is genuinely about the component — recurrence scope routing, the
 * inclusive-picker to exclusive-DTEND conversion, the duration-preserving start
 * field, and the staleness guard on the events fetch.
 *
 * The suite runs pinned to America/New_York (vite.config.ts), so the DST cases
 * below cross a real spring-forward.
 */
import { useState } from 'react'
import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CalendarView } from './CalendarView'
import { DataProvider } from '../data'
import { setCacheUser } from '../cache'
import { api, type CalEvent, type List, type Task } from '../api'
import type { CalendarFit } from '../calendar'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})

const m = vi.mocked(api)

const cal: List = {
  id: 'c1', href: '/c1/', name: 'Work', is_task_list: false, is_calendar: true,
  open_count: 0, task_count: 0, event_count: 1, total: 1, color: '#D9480F',
}

const ev = (o: Partial<CalEvent> = {}): CalEvent => ({
  uid: 'u1', id: 'u1', recurrence_id: null, is_recurring: false, calendar: '/c1/',
  summary: 'Standup', description: null, location: null,
  start: '2026-03-02T09:00:00', start_is_date: false,
  end: '2026-03-02T09:30:00', end_is_date: false, duration: null,
  all_day: false, status: null, busy: true, notify_minutes_before: null, tags: [], has_rrule: false,
  href: '/c1/u1.ics', etag: '"1"', ...o,
})

const taskList: List = {
  id: 'tl1', href: '/tl1/', name: 'Errands', is_task_list: true, is_calendar: false,
  open_count: 2, task_count: 2, event_count: 0, total: 2, color: '#1565C0',
}

const tsk = (o: Partial<Task> = {}): Task => ({
  uid: 't1', list: 'tl1', summary: 'Renew passport', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, priority: null, priority_label: 'none',
  percent_complete: null, due: '2026-03-04', due_is_date: true,
  start: null, start_is_date: true, tags: [], parent: null, children: [],
  child_count: 0, completed_child_count: 0, derived_percent: null,
  pinned: false, sort_order: null,
  // Present on every DTO the server sends; see api.ts's Task.
  completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
  created: null, last_modified: null,
  href: '/tl1/t1.ics', etag: '"1"', ...o,
})

/** A recurring occurrence: what the expander hands the grid for one instance. */
const occurrence = (o: Partial<CalEvent> = {}) => ev({
  id: 'u1::2026-03-09T09:00:00', recurrence_id: '2026-03-09T09:00:00',
  is_recurring: true, has_rrule: true,
  start: '2026-03-09T09:00:00', end: '2026-03-09T09:30:00', ...o,
})

/** userEvent types character-by-character, which a date or datetime-local input
 *  cannot accept; set those directly. */
const setField = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } })

/** `calTaskLists` is controlled like the real App holds it, so a harness that
 *  never fed a change back would test toggles that appear to do nothing. */
function Harness({ taskLists = [] as string[], showDone = false,
  hiddenCalendars = [] as string[], fit = 'dynamic' as CalendarFit,
  onHiddenCalendarsChange = (() => {}) as (next: string[]) => void }) {
  const now = new Date()
  const [cursor, setCursor] = useState(() => new Date(now.getFullYear(), now.getMonth(), 1))
  const [shown, setShown] = useState(taskLists)
  const [done, setDone] = useState(showDone)
  return (
    <DataProvider rev={0} onExpire={vi.fn()}>
      <CalendarView onExpire={vi.fn()} cursor={cursor} onCursorChange={setCursor}
        sideCollapsed={false} onToggleSide={vi.fn()}
        hiddenCalendars={hiddenCalendars} onHiddenCalendarsChange={onHiddenCalendarsChange}
        archivedCalendars={[]} onArchivedCalendarsChange={vi.fn()}
        calTaskLists={shown} onCalTaskListsChange={setShown}
        calShowDone={done} onCalShowDoneChange={() => setDone((v) => !v)}
        fit={fit} />
    </DataProvider>
  )
}

function setup(events?: CalEvent[], props?: {
  taskLists?: string[]; showDone?: boolean; fit?: CalendarFit
  hiddenCalendars?: string[]; onHiddenCalendarsChange?: (next: string[]) => void
}) {
  if (events) m.events.mockResolvedValue(events)
  // The month lives in App now, so the harness has to hold it — a fixed cursor
  // would make the ‹ › buttons no-ops and quietly pass the navigation tests.
  render(<Harness {...props} />)
  return userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
}

/** Open an event's edit modal by clicking its chip. A multi-day span renders one
 *  chip per day it covers; the first is the one on its start day. */
async function openEvent(user: ReturnType<typeof userEvent.setup>, name = 'Standup') {
  await waitFor(() => expect(screen.getAllByTitle(new RegExp(`^${name}`))[0]).toBeInTheDocument())
  await user.click(screen.getAllByTitle(new RegExp(`^${name}`))[0])
  return screen.findByRole('dialog')
}

/** The body of the first write of its kind.
 *
 *  The two calls put it in different places — `patchEvent(cal, uid, body)` and
 *  `createEvent(cal, body)` — and this helper had one index for both. Nothing
 *  noticed because every caller so far asked about a patch; a create came back
 *  `undefined` and `toMatchObject` on it fails as a missing property rather
 *  than as the harness fault it is. */
const body = (call: 'patchEvent' | 'createEvent') => (
  call === 'patchEvent'
    ? m.patchEvent.mock.calls[0][2]
    : m.createEvent.mock.calls[0][1]
) as Record<string, unknown>

beforeEach(() => {
  // The grid opens on today's month, so the clock decides which fixtures render.
  // March 2026 puts the 03-08 spring-forward on screen.
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 2, 5))
  vi.clearAllMocks()
  m.calendars.mockResolvedValue([cal])
  m.lists.mockResolvedValue([taskList])
  m.tasks.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.patchEvent.mockResolvedValue(ev())
  m.createEvent.mockResolvedValue(ev())
  m.deleteEvent.mockResolvedValue(null)
})

afterEach(() => { vi.useRealTimers() })

// ── Busy / Free (iCalendar TRANSP) ──────────────────────────────────────────
//
// The field Apple Calendar calls "Busy/Free". It is not cosmetic: `false` takes
// the event out of the busy set behind the public booking page, so a slot
// sitting on it is offered to whoever holds the link. What the modal sends —
// and, just as much, what it does NOT send — is the whole of that contract on
// this side, because the backend writes TRANSP whenever the key is present.

describe('busy / free', () => {
  const openNew = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(await screen.findByRole('button', { name: 'New event' }))
    return screen.findByRole('dialog', { name: 'New event' })
  }

  it('opens on Busy for a new event, and sends nothing for it', async () => {
    // An event with no TRANSP is busy by RFC 5545's own default, so the control
    // opens agreeing with what the server would store if it were never touched
    // — and leaving it alone writes no property at all.
    const user = setup([])
    await openNew(user)
    expect(screen.getByLabelText('Show as')).toHaveValue('busy')

    await user.type(screen.getByLabelText('Title'), 'Meeting')
    await user.click(screen.getByText('Save'))

    await waitFor(() => expect(m.createEvent).toHaveBeenCalled())
    expect(body('createEvent')).not.toHaveProperty('busy')
  })

  it('sends busy:false when a new event is marked Free', async () => {
    const user = setup([])
    await openNew(user)
    await user.type(screen.getByLabelText('Title'), 'Hold')
    await user.selectOptions(screen.getByLabelText('Show as'), 'free')
    await user.click(screen.getByText('Save'))

    await waitFor(() => expect(m.createEvent).toHaveBeenCalled())
    expect(body('createEvent')).toMatchObject({ busy: false })
  })

  it('opens on Free for an event that is marked free', async () => {
    const user = setup([ev({ busy: false })])
    await openEvent(user)
    expect(screen.getByLabelText('Show as')).toHaveValue('free')
    // …and says what that costs, which is the half a person cannot see.
    expect(screen.getByText(/will not block a slot/i)).toBeInTheDocument()
  })

  it('says nothing about availability while the event blocks', async () => {
    // The hint is only on the arm that changes something. Every event blocks;
    // saying so under every one of them would be a line of chrome in the app's
    // busiest dialog.
    const user = setup([ev()])
    await openEvent(user)
    expect(screen.queryByText(/will not block a slot/i)).not.toBeInTheDocument()
  })

  it('leaves busy off a save that did not touch it', async () => {
    // THE LOAD-BEARING ONE. The backend writes TRANSP whenever the key is
    // present, so a rename that carried `busy` would stamp `TRANSP:OPAQUE` onto
    // an event another CalDAV client had deliberately marked Free — invariant
    // #2, and the same discipline `tagFields` keeps one line above it.
    const user = setup([ev({ busy: false })])
    await openEvent(user)
    // The event really is marked Free — otherwise the assertion below would
    // hold on a build that has no such field at all.
    expect(screen.getByLabelText('Show as')).toHaveValue('free')
    await user.clear(screen.getByLabelText('Title'))
    await user.type(screen.getByLabelText('Title'), 'Renamed')
    await user.click(screen.getByText('Save'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(body('patchEvent')).toMatchObject({ summary: 'Renamed' })
    expect(body('patchEvent')).not.toHaveProperty('busy')
  })

  it('sends it in both directions when it is changed', async () => {
    const user = setup([ev()])
    await openEvent(user)
    await user.selectOptions(screen.getByLabelText('Show as'), 'free')
    await user.click(screen.getByText('Save'))
    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(body('patchEvent')).toMatchObject({ busy: false })
  })

  it('carries the change through a recurring save\'s scope prompt', async () => {
    // The scope prompt renders in place of the form with its state held behind
    // it, so a field answered before the prompt has to survive the round trip
    // through it.
    const user = setup([occurrence()])
    await openEvent(user)
    await user.selectOptions(screen.getByLabelText('Show as'), 'free')
    await user.click(screen.getByText('Save'))
    await user.click(await screen.findByText('All events'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(body('patchEvent')).toMatchObject({ busy: false, scope: 'all' })
  })
})

// ── recurrence scope routing ────────────────────────────────────────────────
// Every per-occurrence write addresses the instance by recurrence_id, so the
// exact body matters: the wrong scope or a missing anchor edits the wrong
// events, and there is no error to notice.

describe('recurrence scope', () => {
  it.each([
    ['This event', 'this'],
    ['This & following', 'thisandfuture'],
  ])('a %s save sends scope %s with the occurrence anchor', async (label, scope) => {
    const user = setup([occurrence()])
    await openEvent(user)
    await user.click(screen.getByText('Save'))
    await user.click(await screen.findByText(label))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(body('patchEvent')).toMatchObject({
      scope, recurrence_id: '2026-03-09T09:00:00',
      start: '2026-03-09T09:00', end: '2026-03-09T09:30',
    })
  })

  it.each([
    ['This event', 'this'],
    ['This & following', 'thisandfuture'],
    ['All events', 'all'],
  ])('a %s delete sends scope %s with the occurrence anchor', async (label, scope) => {
    const user = setup([occurrence()])
    await openEvent(user)
    await user.click(screen.getByText('Delete'))
    await user.click(await screen.findByText(label))

    await waitFor(() => expect(m.deleteEvent).toHaveBeenCalled())
    expect(m.deleteEvent.mock.calls[0][2])
      .toEqual({ recurrence_id: '2026-03-09T09:00:00', scope })
  })

  it('omits the times from an All events save that did not touch them', async () => {
    // The modal shows *this occurrence's* slot. Resending it as the master
    // DTSTART would slide the entire series to this instance's date, so a
    // detail-only edit has to leave the time fields off the wire entirely.
    const user = setup([occurrence()])
    await openEvent(user)
    await user.clear(screen.getByLabelText('Title'))
    await user.type(screen.getByLabelText('Title'), 'Renamed')
    await user.click(screen.getByText('Save'))
    await user.click(await screen.findByText('All events'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    const b = body('patchEvent')
    expect(b).toMatchObject({ scope: 'all', summary: 'Renamed' })
    expect(b).not.toHaveProperty('start')
    expect(b).not.toHaveProperty('end')
    expect(b).not.toHaveProperty('recurrence_id')
  })

  it('includes the times and the anchor when an All events save changed them', async () => {
    // With both, the server shifts the whole series by the same offset.
    const user = setup([occurrence()])
    await openEvent(user)
    setField('End', '2026-03-09T10:30')
    await user.click(screen.getByText('Save'))
    await user.click(await screen.findByText('All events'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(body('patchEvent')).toMatchObject({
      scope: 'all', recurrence_id: '2026-03-09T09:00:00',
      start: '2026-03-09T09:00', end: '2026-03-09T10:30',
    })
  })

  it('sends no scope at all for a non-recurring event', async () => {
    const user = setup([ev()])
    await openEvent(user)
    await user.click(screen.getByText('Save'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(body('patchEvent')).not.toHaveProperty('scope')
  })
})

// ── the all-day picker is inclusive; DTEND is not ───────────────────────────

describe('all-day end conversion', () => {
  it('shows the inclusive last day and writes back an exclusive DTEND', async () => {
    const allDay = ev({
      all_day: true, start_is_date: true, end_is_date: true,
      start: '2026-03-07', end: '2026-03-10',          // covers Mar 7, 8, 9
    })
    const user = setup([allDay])
    await openEvent(user)
    // The picker shows the last day the event actually covers, not the DTEND.
    expect(screen.getByLabelText('End (last day)')).toHaveValue('2026-03-09')

    await user.click(screen.getByText('Save'))
    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(body('patchEvent')).toMatchObject({ start: '2026-03-07', end: '2026-03-10' })
  })

  it('keeps an all-day span the same length when only the start moves', async () => {
    // The span covers Mar 7-9 and contains the 2026-03-08 spring-forward, so it
    // measures 47 hours. Preserving the duration in milliseconds and formatting
    // back to a calendar day landed the end on Apr 2 — the event silently lost a
    // day, on an edit that never touched the end field.
    const allDay = ev({
      all_day: true, start_is_date: true, end_is_date: true,
      start: '2026-03-07', end: '2026-03-10',
    })
    const user = setup([allDay])
    await openEvent(user)
    setField('Start', '2026-04-01')

    expect(screen.getByLabelText('End (last day)')).toHaveValue('2026-04-03')
    await user.click(screen.getByText('Save'))
    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    // Still three days: Apr 1, 2, 3 — exclusive DTEND on the 4th.
    expect(body('patchEvent')).toMatchObject({ start: '2026-04-01', end: '2026-04-04' })
  })

  it('keeps a timed event the same duration when only the start moves', async () => {
    const user = setup([ev({ start: '2026-03-02T09:00:00', end: '2026-03-02T10:30:00' })])
    await openEvent(user)
    setField('Start', '2026-04-01T14:00')

    expect(screen.getByLabelText('End')).toHaveValue('2026-04-01T15:30')
  })
})

// ── a DURATION-only event has a length, even with no DTEND ──────────────────
// DAVx5 and the phone clients write DURATION instead of DTEND. Those arrive
// with `end: null`, and the modal defaulted the end picker to 10:00 — so any
// save, including a pure rename, rewrote the event's end. `_apply_event_fields`
// deletes DURATION whenever a dtend is supplied, so the original span was gone
// for good, and a zero-length event stops blocking booking slots as well.

describe('DURATION-only events', () => {
  it('seeds the end picker from the duration', async () => {
    const user = setup([ev({ start: '2026-03-02T09:00:00', end: null, duration: 'PT1H30M' })])
    await openEvent(user)
    expect(screen.getByLabelText('End')).toHaveValue('2026-03-02T10:30')
  })

  it('preserves the span across an edit that never touched the times', async () => {
    const user = setup([ev({ start: '2026-03-02T09:00:00', end: null, duration: 'PT1H30M' })])
    await openEvent(user)
    setField('Title', 'Renamed')
    await user.click(screen.getByText('Save'))
    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(body('patchEvent')).toMatchObject({
      summary: 'Renamed', start: '2026-03-02T09:00', end: '2026-03-02T10:30',
    })
  })

  it('sends no end at all when the span cannot be derived', async () => {
    // Neither DTEND nor a usable DURATION: sending a fabricated end would
    // destroy whatever the resource actually holds, so the write omits it.
    const user = setup([ev({ start: '2026-03-02T09:00:00', end: null, duration: null })])
    await openEvent(user)
    setField('Title', 'Renamed')
    await user.click(screen.getByText('Save'))
    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    const sent = body('patchEvent') as Record<string, unknown>
    expect(sent.summary).toBe('Renamed')
    expect('end' in sent).toBe(false)
  })
})

// ── the events fetch must not be won by a stale batch ───────────────────────

describe('month navigation', () => {
  it('ignores an older fetch that settles after a newer one', async () => {
    // Two clicks on › put two batches in flight. When the first settled last it
    // painted the month the user had already left — and since the grid clips to
    // the visible six weeks, almost nothing matched a rendered day, so the month
    // came up empty with nothing to correct it.
    const march = ev({ id: 'march', summary: 'March event', start: '2026-03-10T09:00:00',
      end: '2026-03-10T09:30:00' })
    const april = ev({ id: 'april', summary: 'April event', start: '2026-04-10T09:00:00',
      end: '2026-04-10T09:30:00' })

    let releaseFirst: (v: CalEvent[]) => void = () => {}
    const first = new Promise<CalEvent[]>((res) => { releaseFirst = res })
    m.events.mockReturnValueOnce(first).mockResolvedValue([april])

    const user = setup()
    await screen.findByText(/^Today$/)
    await user.click(screen.getByRole('button', { name: '›' }))
    await waitFor(() => expect(m.events).toHaveBeenCalledTimes(2))

    // April's batch settles first, so April is what the user is looking at.
    await waitFor(() => expect(screen.getByText('April event')).toBeInTheDocument())

    // Now March's — the month the user already navigated away from — arrives.
    releaseFirst([march])
    await act(async () => { await first })

    expect(screen.getByText('April event')).toBeInTheDocument()
    expect(screen.queryByText('March event')).not.toBeInTheDocument()
  })
})

// ── tasks on the grid ───────────────────────────────────────────────────────
// The calendar had no tasks on it before, so the setting that puts them there
// is an allowlist: nothing appears until a list is opted in.

describe('<CalendarView> tasks', () => {
  const chips = () =>
    [...document.querySelectorAll('.cal-task')].map((n) => n.textContent)

  it('draws nothing until a task list is opted in', async () => {
    m.tasks.mockResolvedValue([tsk()])
    setup([])
    await waitFor(() => expect(m.tasks).toHaveBeenCalled())
    expect(chips()).toEqual([])
  })

  it('draws tasks of an opted-in list on their due day', async () => {
    m.tasks.mockResolvedValue([tsk()])
    setup([], { taskLists: ['tl1'] })
    await waitFor(() => expect(chips()).toHaveLength(1))
    expect(chips()[0]).toContain('Renew passport')
    // The chip sits in the cell for the 4th, not wherever the grid starts.
    const cell = document.querySelector('.cal-task')!.closest('.cal-cell')!
    expect(cell.querySelector('.daynum')!.textContent).toBe('4')
  })

  it('leaves out a task from a list that is not opted in', async () => {
    m.lists.mockResolvedValue([taskList, { ...taskList, id: 'tl2', href: '/tl2/', name: 'Work tasks' }])
    // Per list: the provider fans out one request each, so a single mocked
    // array would come back once per list and duplicate every task.
    m.tasks.mockImplementation(async (id: string) =>
      (id === 'tl1' ? [tsk()] : [tsk({ uid: 't2', list: 'tl2', summary: 'File taxes' })]))
    setup([], { taskLists: ['tl1'] })
    await waitFor(() => expect(chips()).toHaveLength(1))
    expect(chips()[0]).toContain('Renew passport')
  })

  it('hides completed tasks by default and shows them on request', async () => {
    m.tasks.mockResolvedValue([tsk(), tsk({ uid: 't2', summary: 'Post letter', completed: true })])
    const user = setup([], { taskLists: ['tl1'] })
    await waitFor(() => expect(chips()).toHaveLength(1))

    await user.click(screen.getByRole('button', { name: /^Completed/ }))
    await waitFor(() => expect(chips()).toHaveLength(2))
    expect(document.querySelector('.cal-task.done')).toBeInTheDocument()
  })

  it('shows a timed due, and nothing for an all-day one', async () => {
    m.tasks.mockResolvedValue([
      tsk({ due: '2026-03-04T14:30', due_is_date: false }),
      tsk({ uid: 't2', summary: 'Bin day', due: '2026-03-05', due_is_date: true }),
    ])
    setup([], { taskLists: ['tl1'] })
    await waitFor(() => expect(chips()).toHaveLength(2))
    expect(chips()[0]).toMatch(/2:30\s?PM/)
    expect(chips()[1]).not.toMatch(/\d:\d\d/)
  })

  it('opens the task editor when a chip is clicked', async () => {
    m.tasks.mockResolvedValue([tsk()])
    m.patchTask.mockResolvedValue(tsk({ summary: 'Renew passport!' }))
    const user = setup([], { taskLists: ['tl1'] })
    await waitFor(() => expect(chips()).toHaveLength(1))

    await user.click(document.querySelector('.cal-task') as HTMLElement)
    const modal = await screen.findByRole('dialog', { name: 'Task' })
    expect(within(modal).getByLabelText('Title')).toHaveValue('Renew passport')

    // …and a save goes down the tasks tab's own write path.
    fireEvent.change(within(modal).getByLabelText('Title'), { target: { value: 'Renew passport!' } })
    await user.click(within(modal).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(m.patchTask).toHaveBeenCalled())
    expect(m.patchTask.mock.calls[0][2]).toEqual({ summary: 'Renew passport!' })
  })

  it('counts tasks and events together in "+N more"', async () => {
    // The cap is over both kinds, so the remainder it reports is the real one.
    const evs = Array.from({ length: 3 }, (_, i) =>
      ev({ uid: `e${i}`, id: `e${i}`, summary: `Ev ${i}`,
        start: '2026-03-04T09:00:00', end: '2026-03-04T09:30:00' }))
    m.tasks.mockResolvedValue(Array.from({ length: 3 }, (_, i) =>
      tsk({ uid: `t${i}`, summary: `Task ${i}` })))
    setup(evs, { taskLists: ['tl1'] })
    // 3 events + 3 tasks on the 4th, 4 shown, so 2 left over.
    expect(await screen.findByRole('button', { name: '+2 more' })).toBeInTheDocument()
  })

  it('lists both kinds in the day popover', async () => {
    const evs = Array.from({ length: 5 }, (_, i) =>
      ev({ uid: `e${i}`, id: `e${i}`, summary: `Ev ${i}`,
        start: '2026-03-04T09:00:00', end: '2026-03-04T09:30:00' }))
    m.tasks.mockResolvedValue([tsk()])
    const user = setup(evs, { taskLists: ['tl1'] })
    await user.click(await screen.findByRole('button', { name: '+2 more' }))
    const pop = await screen.findByRole('dialog')
    expect(within(pop).getByText('Renew passport')).toBeInTheDocument()
    expect(within(pop).getByText('Ev 0')).toBeInTheDocument()
  })
})

// ── the fixed window ────────────────────────────────────────────────────────
// The shape of the grid is CSS's job; what the component owns is the class that
// turns it on and the chip cap that has to hold when nothing is measurable.
// jsdom lays nothing out — every height it reports is 0 — so it exercises
// exactly the path a real browser takes on its first paint.

describe('<CalendarView> calendar window', () => {
  const busy = () => Array.from({ length: 6 }, (_, i) =>
    ev({ uid: `e${i}`, id: `e${i}`, summary: `Ev ${i}`,
      start: '2026-03-04T09:00:00', end: '2026-03-04T09:30:00' }))

  it('leaves the grid free to grow by default', async () => {
    setup(busy())
    await screen.findByRole('button', { name: '+2 more' })
    expect(document.querySelector('.cal-scroll')).not.toHaveClass('fixed')
  })

  it('pins the grid to the pane when the account asked for it', async () => {
    setup(busy(), { fit: 'fixed' })
    await screen.findByRole('button', { name: /more$/ })
    expect(document.querySelector('.cal-scroll')).toHaveClass('fixed')
  })

  it('falls back to the shipped cap while the cell cannot be measured', async () => {
    // An unlaid-out grid answers null, not zero, so the cap holds at 4 rather
    // than hiding all six events behind "+6 more" on the first paint. Three
    // chips, not four: a fixed cell cannot grow, so the button comes out of the
    // same four slots.
    setup(busy(), { fit: 'fixed' })
    expect(await screen.findByRole('button', { name: '+3 more' })).toBeInTheDocument()
    expect(document.querySelectorAll('.cal-ev')).toHaveLength(3)
  })
})

describe('<CalendarView> chip text', () => {
  // The whole title always reaches the DOM; the ellipsis is painted by CSS over
  // what will not fit. Cutting the string instead would break Arabic letter
  // joining — the last surviving letter falls back to a wider isolated form, so
  // the "shortened" title can render longer than the one it shortened.
  const arabic = 'اجتماع الفريق الأسبوعي لمراجعة المشروع'

  it('keeps a long title whole and lays it out right to left', async () => {
    setup([ev({ summary: arabic })])
    const chip = await waitFor(() => {
      const el = document.querySelector('.cal-ev')
      expect(el).not.toBeNull()
      return el as HTMLElement
    })
    expect(chip).toHaveAttribute('dir', 'rtl')
    expect(chip.textContent).toContain(arabic)          // nothing truncated it
    expect(chip.textContent).not.toContain('…')
    expect(chip).toHaveAttribute('title', arabic)       // and hover has it in full
  })

  it('leaves a left-to-right title undirected', async () => {
    setup([ev({ summary: 'Weekly standup' })])
    await waitFor(() => expect(document.querySelector('.cal-ev')).not.toBeNull())
    expect(document.querySelector('.cal-ev')).not.toHaveAttribute('dir')
  })

  it('isolates a task title the same way', async () => {
    m.tasks.mockResolvedValue([tsk({ summary: arabic })])
    setup([], { taskLists: ['tl1'] })
    await waitFor(() => expect(document.querySelector('.cal-task')).not.toBeNull())
    const chip = document.querySelector('.cal-task') as HTMLElement
    expect(chip).toHaveAttribute('dir', 'rtl')
    expect(chip.querySelector('bdi')!.textContent).toBe(arabic)
  })
})

describe('<CalendarView> tasks sidebar', () => {
  it('toggles a list onto the calendar, reading the opposite way from a hidden set', async () => {
    m.tasks.mockResolvedValue([tsk()])
    const user = setup([])
    const row = await screen.findByRole('checkbox', { name: /Errands/ })
    // Off by default — the inverse of every other row in this sidebar.
    expect(row).toHaveAttribute('aria-checked', 'false')

    await user.click(row)
    expect(row).toHaveAttribute('aria-checked', 'true')
    await waitFor(() => expect(document.querySelectorAll('.cal-task')).toHaveLength(1))

    await user.click(row)
    expect(row).toHaveAttribute('aria-checked', 'false')
    await waitFor(() => expect(document.querySelectorAll('.cal-task')).toHaveLength(0))
  })

  it('offers no way to rename, recolor or delete a task list from here', async () => {
    // Those belong to the tasks tab. A reorder here would PROPPATCH
    // calendar-order onto the task collections.
    m.tasks.mockResolvedValue([tsk()])
    setup([])
    const row = await screen.findByRole('checkbox', { name: /Errands/ })
    expect(row.querySelector('.side-edit')).toBeNull()
    expect(row).not.toHaveAttribute('draggable', 'true')
  })
})

// ── Stage 4 backlog closure (docs/AUDIT.md) ────────────────────────────────

describe('stage 4 — chip identity', () => {
  // AUDIT closed: CalendarView.tsx:470 — chips keyed on the bare id.
  it('renders both copies when one UID lives in two calendars', async () => {
    // `id` is unique per rendered instance of a SERIES, and a UID is only unique
    // within one collection — so an event copied to (or subscribed from) a
    // second calendar gave two chips one React key. React drops one, and can
    // bind the wrong click target to the survivor.
    const warn = vi.spyOn(console, 'error').mockImplementation(() => {})
    setup([
      ev({ uid: 'shared', id: 'shared', calendar: '/c1/', summary: 'Standup' }),
      ev({ uid: 'shared', id: 'shared', calendar: '/c2/', summary: 'Standup' }),
    ])
    await waitFor(() =>
      expect(screen.getAllByTitle(/^Standup/).length).toBeGreaterThanOrEqual(2))
    expect(warn.mock.calls.flat().join(' ')).not.toMatch(/same key/i)
    warn.mockRestore()
  })
})

// ── an event moved into a hidden calendar must not just vanish ──────────────
// The modal's Calendar picker is populated from `visibleCals`, which includes
// calendars the user has HIDDEN — hidden is a pure render filter, not an
// exclusion from the list. The create branch reveals the target for exactly
// this reason ("Don't let a fresh event vanish into a hidden calendar"); the
// move branch did not, so picking a hidden calendar for an existing event
// dropped it out of the month grid, the mobile agenda and the day popovers with
// no feedback at all.

describe('moving into a hidden calendar', () => {
  const other: List = {
    id: 'c2', href: '/c2/', name: 'Personal', is_task_list: false, is_calendar: true,
    open_count: 0, task_count: 0, event_count: 0, total: 0, color: '#1565C0',
  }

  it('reveals the destination after a successful move', async () => {
    const onHiddenCalendarsChange = vi.fn()
    m.calendars.mockResolvedValue([cal, other])
    m.moveEvent.mockResolvedValue(ev({ calendar: '/c2/' }))
    const user = setup([ev()], { hiddenCalendars: ['c2'], onHiddenCalendarsChange })

    await openEvent(user)
    await user.selectOptions(screen.getByLabelText('Calendar'), 'c2')
    await user.click(screen.getByText('Save'))

    await waitFor(() => expect(m.moveEvent).toHaveBeenCalled())
    expect(onHiddenCalendarsChange).toHaveBeenCalledWith([])
  })

  it('leaves the hidden set alone when the destination is already visible', async () => {
    const onHiddenCalendarsChange = vi.fn()
    m.calendars.mockResolvedValue([cal, other])
    m.moveEvent.mockResolvedValue(ev({ calendar: '/c2/' }))
    const user = setup([ev()], { hiddenCalendars: [], onHiddenCalendarsChange })

    await openEvent(user)
    await user.selectOptions(screen.getByLabelText('Calendar'), 'c2')
    await user.click(screen.getByText('Save'))

    await waitFor(() => expect(m.moveEvent).toHaveBeenCalled())
    expect(onHiddenCalendarsChange).not.toHaveBeenCalled()
  })
})

// ── Escape, at both dialogs and at both depths ──────────────────────────────
// This file holds TWO `role="dialog" aria-modal="true"` scrims: the event
// editor, and the prompt a recurring drag parks in. The editor's Escape used to
// be bound flat — one `useEscape(onClose)` at the component level, live even
// while the scope prompt was showing in place of the form — so Escape at the
// prompt threw away a filled-in event instead of backing out of the question.
// The drag prompt had no Escape at all, and the structural guard could not see
// that: it grepped the FILE, and the editor below already satisfied it.

describe('Escape unwinds one step', () => {
  it('backs out of the save-scope prompt with the form still filled in', async () => {
    const user = setup([occurrence()])
    await openEvent(user)
    const title = screen.getByLabelText('Title')
    await user.clear(title)
    await user.type(title, 'Renamed standup')
    await user.click(screen.getByText('Save'))
    expect(await screen.findByText('Apply changes to which events?')).toBeInTheDocument()

    fireEvent.keyDown(window, { key: 'Escape' })

    // One step back: the question is gone, the form is not, and the edit
    // survived. Nothing was written — Escape is not an answer to the prompt.
    expect(screen.queryByText('Apply changes to which events?')).toBeNull()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByLabelText('Title')).toHaveValue('Renamed standup')
    expect(m.patchEvent).not.toHaveBeenCalled()

    // A second Escape is at the top level, and closes the editor.
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('backs out of the delete-scope prompt the same way', async () => {
    const user = setup([occurrence()])
    await openEvent(user)
    await user.click(screen.getByText('Delete'))
    expect(await screen.findByText('Delete which events?')).toBeInTheDocument()

    fireEvent.keyDown(window, { key: 'Escape' })

    expect(screen.queryByText('Delete which events?')).toBeNull()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(m.deleteEvent).not.toHaveBeenCalled()
  })

  it('closes the drag-scope prompt, which is a second dialog in this file', async () => {
    setup([occurrence()])
    await waitFor(() => expect(screen.getAllByTitle(/^Standup/)[0]).toBeInTheDocument())
    const chip = screen.getAllByTitle(/^Standup/)[0]
    // The occurrence sits on the 9th; drop it on the 10th. `dataTransfer` is
    // jsdom's gap, not the component's — the handler only calls setData on it.
    const target = Array.from(document.querySelectorAll('.cal-cell')).find(
      (c) => !c.classList.contains('dim')
        && c.querySelector('.daynum')?.textContent === '10')
    expect(target, 'could not find the 10th in the grid').toBeTruthy()
    fireEvent.dragStart(chip, { dataTransfer: { setData: () => {}, effectAllowed: 'move' } })
    fireEvent.drop(target!)

    expect(await screen.findByText('Apply the change to which events?')).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByText('Apply the change to which events?')).toBeNull()
    // Escape declines the move; it does not silently pick a scope.
    expect(m.patchEvent).not.toHaveBeenCalled()
  })
})
