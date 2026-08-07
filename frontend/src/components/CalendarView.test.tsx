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
import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CalendarView } from './CalendarView'
import { api, type CalEvent, type List } from '../api'

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
  end: '2026-03-02T09:30:00', end_is_date: false,
  all_day: false, status: null, tags: [], has_rrule: false,
  href: '/c1/u1.ics', etag: '"1"', ...o,
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

function setup(events?: CalEvent[]) {
  if (events) m.events.mockResolvedValue(events)
  render(
    <CalendarView rev={0} onExpire={vi.fn()}
      sideCollapsed={false} onToggleSide={vi.fn()}
      hiddenCalendars={[]} onHiddenCalendarsChange={vi.fn()}
      archivedCalendars={[]} onArchivedCalendarsChange={vi.fn()} />,
  )
  return userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
}

/** Open an event's edit modal by clicking its chip. A multi-day span renders one
 *  chip per day it covers; the first is the one on its start day. */
async function openEvent(user: ReturnType<typeof userEvent.setup>, name = 'Standup') {
  await waitFor(() => expect(screen.getAllByTitle(new RegExp(`^${name}`))[0]).toBeInTheDocument())
  await user.click(screen.getAllByTitle(new RegExp(`^${name}`))[0])
  return screen.findByRole('dialog')
}

const body = (call: 'patchEvent' | 'createEvent') =>
  (call === 'patchEvent' ? m.patchEvent : m.createEvent).mock.calls[0][2] as Record<string, unknown>

beforeEach(() => {
  // The grid opens on today's month, so the clock decides which fixtures render.
  // March 2026 puts the 03-08 spring-forward on screen.
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 2, 5))
  vi.clearAllMocks()
  m.calendars.mockResolvedValue([cal])
  m.events.mockResolvedValue([])
  m.patchEvent.mockResolvedValue(ev())
  m.createEvent.mockResolvedValue(ev())
  m.deleteEvent.mockResolvedValue(null)
})

afterEach(() => { vi.useRealTimers() })

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
