/**
 * The 2026-08-19 sweep, stage 4a: user-visible correctness in the calendar,
 * the scheduling editor and the appearance layer.
 *
 * **These nine findings are OPEN.** Every test below asserts the behaviour the
 * app SHOULD have and fails against the code as it stands, so each is marked
 * `it.fails` — the file passes while a finding is open, and the moment one is
 * fixed its pin XPASSes, the file goes red, and somebody has to tick the
 * finding off in docs/AUDIT.md and drop the marker. Same contract as
 * `backlog.stage4.test.tsx`, whose api-mocking preamble this copies.
 *
 * The theme is one class of defect: the screen and the wire disagree with what
 * the user did. A month that failed to load once is recorded as loaded and
 * never asked for again; a resize grip clamped to the window edge truncates a
 * six-month block when it is released on its own cell; the dashboard's mini
 * calendar keeps painting yesterday's dots while every other module on the same
 * page refreshes; a rejected booking-link save bricks the form the user just
 * filled in; the availability grid builds a week the server refuses and
 * silently deletes a range typed backwards; a corner radius set in light mode
 * evaporates on the flip to dark; an overflowing DURATION is written to the API
 * as the literal string "NaN-NaN-NaNTNaN:NaN"; and ticking "all day" on an
 * event that ends at midnight quietly gives it a second day.
 *
 * All nine are BEHAVIOURAL: each drives the real component or the real exported
 * function and asserts what a user or the API would see. None reads source
 * text. Where a finding admits more than one correct repair the assertion names
 * the outcome, not the repair — STAGES.md records what pins that only accept
 * the fix you imagined cost the last time. Two ordinary passing tests sit
 * alongside the pins as controls, marked as such: they exist so a "fix" that
 * over-corrects (rejecting real colours, sharing tokens that are meant to be
 * per-mode) cannot satisfy its pin by breaking something else.
 */
import { useState } from 'react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { isValidToken, resolve, sanitizeTokens, type Appearance, type CustomTheme } from './appearance'
import { durationMs, endFromDuration } from './calendar'
import { DataProvider } from './data'
import { setCacheUser } from './cache'
import { AppearancePanel } from './components/AppearancePanel'
import { CalendarView } from './components/CalendarView'
import { HomeView } from './components/HomeView'
import { SchedulingView } from './components/SchedulingView'
import type { DashboardModule } from './dashboard'
import { api, HttpError, type BookingLinkInput, type CalEvent, type List, type Task } from './api'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)

const cal: List = {
  id: 'c1', href: '/c1/', name: 'Work', is_task_list: false, is_calendar: true,
  open_count: 0, task_count: 0, event_count: 1, total: 1, color: '#D9480F',
}
const taskList: List = {
  id: 'tl1', href: '/tl1/', name: 'Errands', is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: '#1565C0',
}

const ev = (o: Partial<CalEvent> = {}): CalEvent => ({
  uid: 'u1', id: 'u1', recurrence_id: null, is_recurring: false, calendar: '/c1/',
  summary: 'Standup', description: null, location: null,
  start: '2026-03-02T09:00:00', start_is_date: false,
  end: '2026-03-02T09:30:00', end_is_date: false, duration: null,
  all_day: false, status: null, tags: [], has_rrule: false,
  href: '/c1/u1.ics', etag: '"1"', ...o,
})

const theme = (o: Partial<CustomTheme> = {}): CustomTheme => ({
  id: 't1', name: 'Mine', base: 'light', light: {}, dark: {}, ...o,
})

/** userEvent has to be told about the fake clock or every await hangs. */
const setupUser = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

beforeEach(() => {
  // The calendar grid opens on today's month, so the clock decides which
  // fixtures render. March 2026 begins on a Sunday, which makes the six-week
  // window exactly 2026-03-01 … 2026-04-11 — the clamp the resize pin is about.
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 2, 5))
  vi.clearAllMocks()
  setCacheUser('')
  localStorage.clear()
  m.calendars.mockResolvedValue([cal])
  m.lists.mockResolvedValue([taskList])
  m.tasks.mockResolvedValue([] as Task[])
  m.events.mockResolvedValue([])
  m.patchEvent.mockResolvedValue(ev())
  m.createEvent.mockResolvedValue(ev())
  m.deleteEvent.mockResolvedValue(null as never)
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
  // Implementations survive clearAllMocks, so a rejection set inside one test
  // would leak into the next and make this file order-dependent.
  m.createSchedulingLink.mockResolvedValue({} as never)
})

afterEach(() => { vi.useRealTimers() })

// ── the calendar tab ────────────────────────────────────────────────────────

/** The Calendar tab with its month held above it, exactly as App holds it — a
 *  fixed cursor would make ‹ › no-ops and quietly pass the navigation pin. */
function CalHarness({ rev = 0 }: { rev?: number }) {
  const now = new Date()
  const [cursor, setCursor] = useState(() => new Date(now.getFullYear(), now.getMonth(), 1))
  const [shown, setShown] = useState<string[]>([])
  return (
    <DataProvider rev={rev} onExpire={vi.fn()}>
      <CalendarView onExpire={vi.fn()} cursor={cursor} onCursorChange={setCursor}
        sideCollapsed={false} onToggleSide={vi.fn()}
        hiddenCalendars={[]} onHiddenCalendarsChange={vi.fn()}
        archivedCalendars={[]} onArchivedCalendarsChange={vi.fn()}
        calTaskLists={shown} onCalTaskListsChange={setShown}
        calShowDone={false} onCalShowDoneChange={vi.fn()}
        fit="dynamic" />
    </DataProvider>
  )
}

function openCalendar(events?: CalEvent[]) {
  if (events) m.events.mockResolvedValue(events)
  render(<CalHarness />)
  return setupUser()
}

/** Wait for an event's chips to be on the grid. Separate from `openEvent`
 *  because the drag pin wants the chip in place without opening its modal. */
async function chipsFor(name: string) {
  await waitFor(() => expect(screen.getAllByTitle(new RegExp(`^${name}`))[0]).toBeInTheDocument())
}

/** Open an event's edit modal by clicking its chip. A multi-day span renders
 *  one chip per day it covers; the first is the one on its start day. */
async function openEvent(user: ReturnType<typeof setupUser>, name = 'Standup') {
  await waitFor(() => expect(screen.getAllByTitle(new RegExp(`^${name}`))[0]).toBeInTheDocument())
  await user.click(screen.getAllByTitle(new RegExp(`^${name}`))[0])
  return screen.findByRole('dialog')
}

const patchBody = () => m.patchEvent.mock.calls[0][2] as Record<string, unknown>

describe('2026-08-19 — the calendar grid', () => {
  // ── AUDIT (open): data.tsx:576 — a failed events fetch records the month as
  //    "asked", so the grid stays blank with no retry path ─────────────────
  it('re-requests a month whose first fetch failed', async () => {
    // EVIDENCE. `requestWindow` writes the window into `asked` BEFORE issuing
    // the fetch and short-circuits every later request while `rev` and the
    // calendar set are unchanged. `fetchWindow` deletes from `gen` and
    // `inflight` but never from `asked`, and the fan-out is a `Promise.all`, so
    // one 502 through the tunnel leaves the month recorded as fetched with
    // nothing in `windows` — `eventsFor` then falls back to the disk mirror,
    // which on a fresh browser is empty. Reproduced by hand: mount on March
    // (one call, rejects), page to April (two calls, April paints), page back
    // to March — no third call, and March is blank forever. Only an SSE bump,
    // archiving a calendar or an event edit ever recovers it.
    //
    // The assertion is the month on screen, not the call count: any correct
    // repair — dropping the `asked` record on failure, retrying, recording only
    // successes — has to end with the user seeing their events.
    //
    // WIDENED. The single-failure case below passed against a repair that
    // recovers exactly once, so a second failure is driven too: a flaky tunnel
    // does not fail once and then behave. And the dedupe is asserted to SURVIVE
    // — a month that succeeded is not re-requested when the user pages back to
    // it — so "delete the record unconditionally" cannot satisfy this either.
    // Both directions matter: this provider sits under every tab, and a
    // request storm here is finding 22 all over again.
    const march = ev({ id: 'march', summary: 'March event',
      start: '2026-03-10T09:00:00', end: '2026-03-10T09:30:00' })
    m.events
      .mockRejectedValueOnce(new Error('502 bad gateway'))
      .mockResolvedValueOnce([])                       // April, first visit
      .mockRejectedValueOnce(new Error('502 bad gateway'))   // March, second try
      .mockResolvedValue([march])

    const user = openCalendar()
    await screen.findByText(/^Today$/)
    await waitFor(() => expect(m.events).toHaveBeenCalledTimes(1))

    const next = () => screen.getByRole('button', { name: '›' })
    const prev = () => screen.getByRole('button', { name: '‹' })

    await user.click(next())                                    // April
    await waitFor(() => expect(m.events).toHaveBeenCalledTimes(2))
    await user.click(prev())                                    // back to March — fails again
    await waitFor(() => expect(m.events).toHaveBeenCalledTimes(3))
    await user.click(next())                                    // April again: already have it
    await user.click(prev())                                    // March, third try — succeeds

    expect(await screen.findByText('March event')).toBeInTheDocument()

    // April succeeded on its first visit, so neither return trip may re-request
    // it. Four calls total: March, April, March, March.
    expect(m.events).toHaveBeenCalledTimes(4)
  })

  // ── AUDIT (open): CalendarView.tsx:556 — the resize grip on a span that runs
  //    past the six-week window truncates it when released on its own cell ──
  it('does not truncate a window-clipped span dropped where its grip is drawn', async () => {
    // EVIDENCE. The grid clamps a long event's grip to the last visible day
    // (`evLast > lastKey ? lastKey : evLast`), but `dragBody` compares the newly
    // built end against the event's REAL stored end, so for any span that
    // continues past the rendered grid, grabbing the grip and letting go without
    // moving is not the no-op it is for every other event: it PATCHes a DTEND at
    // the window edge and deletes the rest. Reproduced by hand on an all-day
    // 'Sabbatical' 2026-03-01 → 2026-09-01: the grip renders in the 2026-04-11
    // cell (days[41]) and a dragStart + drop on that same cell sent
    // {"start":"2026-03-01","end":"2026-04-12"} — six months cut to six weeks by
    // a drag that moved zero pixels, with no confirmation and no undo.
    //
    // Correct is a no-op, which is what the same gesture already does for an
    // unclipped event. Whether that comes from teaching `dragBody` the clamp or
    // from not drawing a grip that cannot honestly mean "the last day", nothing
    // may reach the API.
    openCalendar([ev({
      uid: 'sab', id: 'sab', summary: 'Sabbatical', all_day: true,
      start: '2026-03-01', start_is_date: true,
      end: '2026-09-01', end_is_date: true,
    })])
    await chipsFor('Sabbatical')

    const cells = document.querySelectorAll('.cal-cell')
    expect(cells).toHaveLength(42)
    const lastCell = cells[41]                       // 2026-04-11, the window edge
    const grip = lastCell.querySelector('.ev-resize')
    expect(grip).toBeTruthy()

    // jsdom builds a DragEvent with no dataTransfer, and the handler sets data
    // on it (Firefox needs data present to start a drag at all).
    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }
    fireEvent.dragStart(grip!, { dataTransfer })
    fireEvent.drop(lastCell, { dataTransfer })
    await act(async () => { await Promise.resolve() })

    // Asserted on the calls array rather than `not.toHaveBeenCalled()` so the
    // failure prints the DTEND that was written.
    expect(m.patchEvent.mock.calls).toEqual([])
  })

  // WIDENING: the same gesture on a TIMED clipped span. The all-day case above
  // goes through `dragBody`'s `ev.all_day` branch; this one goes through the
  // `else` that reads a time off the old end, so a repair placed in one branch
  // does not cover the other.
  it('does not truncate a window-clipped TIMED span dropped on its own cell', async () => {
    openCalendar([ev({
      uid: 'proj', id: 'proj', summary: 'Project',
      start: '2026-03-01T09:00:00', end: '2026-09-01T17:00:00',
    })])
    await chipsFor('Project')

    const cells = document.querySelectorAll('.cal-cell')
    const lastCell = cells[41]
    const grip = lastCell.querySelector('.ev-resize')
    expect(grip).toBeTruthy()

    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }
    fireEvent.dragStart(grip!, { dataTransfer })
    fireEvent.drop(lastCell, { dataTransfer })
    await act(async () => { await Promise.resolve() })

    expect(m.patchEvent.mock.calls).toEqual([])
  })

  // POSITIVE CONTROL — the case that stops "return null for anything clipped".
  // Shortening a long span from the visible window is a real gesture and the
  // only one available for an event whose true end is months away; a repair
  // that refuses every drop on a clipped event takes it away silently. This is
  // also why the cheap alternative the finding offers (do not draw the grip at
  // all) is wrong: the pin above asserts the grip exists, and this asserts it
  // still does something.
  it('still resizes a window-clipped span dropped on an earlier cell', async () => {
    openCalendar([ev({
      uid: 'sab', id: 'sab', summary: 'Sabbatical', all_day: true,
      start: '2026-03-01', start_is_date: true,
      end: '2026-09-01', end_is_date: true,
    })])
    await chipsFor('Sabbatical')

    const cells = document.querySelectorAll('.cal-cell')
    const lastCell = cells[41]                       // where the grip is drawn
    const grip = lastCell.querySelector('.ev-resize')
    const target = cells[20]                         // 2026-03-21, well inside the window

    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }
    fireEvent.dragStart(grip!, { dataTransfer })
    fireEvent.drop(target, { dataTransfer })
    await act(async () => { await Promise.resolve() })

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    // DTEND is exclusive: dropping on the 21st means the span ends on the 22nd.
    expect(patchBody()).toMatchObject({ end: '2026-03-22' })
  })

  // Control (passes today): an event whose real end IS the last visible day is
  // not clipped, and dropping its grip where it already sits is the ordinary
  // no-op. A repair keyed on the drop cell alone rather than on the event's
  // true end would break this.
  it('is still a no-op to drop an unclipped grip on its own last cell', async () => {
    openCalendar([ev({
      uid: 'wk', id: 'wk', summary: 'Workshop', all_day: true,
      start: '2026-04-09', start_is_date: true,
      end: '2026-04-12', end_is_date: true,          // exclusive: last day is 04-11
    })])
    await chipsFor('Workshop')

    const cells = document.querySelectorAll('.cal-cell')
    const lastCell = cells[41]                       // 2026-04-11
    const grip = lastCell.querySelector('.ev-resize')
    expect(grip).toBeTruthy()

    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }
    fireEvent.dragStart(grip!, { dataTransfer })
    fireEvent.drop(lastCell, { dataTransfer })
    await act(async () => { await Promise.resolve() })

    expect(m.patchEvent.mock.calls).toEqual([])
  })

  // ── AUDIT (open): calendar.ts:70 — endFromDuration returns the string
  //    "NaN-NaN-NaNTNaN:NaN" instead of null when the duration overflows ────
  it('sends no fabricated end for a DURATION that overflows the calendar', async () => {
    // EVIDENCE. `endFromDuration` guards `isNaN` on the START but never on the
    // computed end, so a DURATION large enough to push `start + ms` outside the
    // ±8.64e15 ms Date range formats as "NaN-NaN-NaNTNaN:NaN" — a truthy string
    // where the docstring promises null. That truthiness defeats the modal's
    // `endUnknown` protection ("rather than send a fabricated end and destroy
    // whatever the resource actually holds, leave `end` out of the write"), the
    // End picker renders blank, and any save — including a pure rename — PATCHes
    // the NaN string. `_parse_datelike` answers 422 "invalid date/datetime", so
    // the user's rename is lost behind a cryptic toast. DURATION arrives off the
    // wire from other CalDAV clients (DAVx5, the phone clients), and neither
    // `durationMs` nor `endFromDuration` had a direct test.
    //
    // The assertion is what goes on the wire: an `end` the API can parse, or no
    // `end` at all. Both are correct; the NaN string is not.
    const user = openCalendar([ev({
      start: '2026-03-02T09:00:00', end: null, duration: 'P100000000D',
    })])
    await openEvent(user)
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Renamed' } })
    await user.click(screen.getByText('Save'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    const sent = patchBody()
    expect(sent.summary).toBe('Renamed')
    expect(String(sent.end ?? '')).toMatch(/^(\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?)?$/)
    // And the helper's own documented contract — "or null if it cannot be
    // derived". Asserted as falsy, not as `null`, so a repair that returns
    // undefined or '' is equally acceptable.
    expect(endFromDuration('2026-03-02T09:00:00', 'P100000000D')).toBeFalsy()

    // The SECOND overflow, and a different guard: a day count too large for
    // Number itself makes `ms` Infinity before any Date is built, so
    // `endFromDuration`'s isNaN check on the result would still not be enough —
    // `durationMs` has to refuse it. Widened here because the original drove one
    // input through one guard and would have passed against half the repair.
    expect(durationMs(`P${'9'.repeat(400)}D`)).toBeNull()
    expect(endFromDuration('2026-03-02T09:00:00', `P${'9'.repeat(400)}D`)).toBeFalsy()
  })

  // Control (passes today except where noted, and must stay passing): the
  // table the finding says neither helper ever had. Written as an ordinary
  // test because that is what it is — the grammar below is already handled
  // correctly, and the gap was that nothing said so, which let the overflow
  // case above hide. A repair that tightens the parser to reject the overflow
  // by rejecting more of the grammar breaks this.
  it('parses every DURATION shape RFC 5545 allows, and refuses the rest', () => {
    const H = 3600000
    for (const [raw, ms] of [
      ['P1W', 7 * 24 * H],
      ['P1D', 24 * H],
      ['P1DT2H30M', 26.5 * H],
      ['PT1H30M', 1.5 * H],
      ['PT0S', 0],                   // legal, and zero — NOT the same as null
      ['-PT1H', -H],
      ['+PT1H', H],
    ] as Array<[string, number]>) {
      expect(durationMs(raw)).toBe(ms)
    }
    for (const bad of ['P', 'PT', '', '   ', 'P1.5D', 'P1W2D', '1H', 'PT1H30', null, undefined]) {
      expect(durationMs(bad as string | null | undefined)).toBeNull()
    }

    // …and the wrapper's contract on top of it.
    expect(endFromDuration('2026-03-02T09:00:00', 'PT1H30M')).toBe('2026-03-02T10:30')
    expect(endFromDuration('2026-03-02T09:00:00', 'PT0S')).toBe('2026-03-02T09:00')
    expect(endFromDuration('2026-03-02T09:00:00', 'P')).toBeNull()
    expect(endFromDuration('not-a-date', 'PT1H')).toBeNull()
  })

  // ── AUDIT (open): CalendarView.tsx:777 — ticking "all day" on a timed event
  //    that ends at midnight adds a day the grid never showed ───────────────
  it('keeps a midnight-ending event on its one day when it is made all-day', async () => {
    // EVIDENCE. `endIsExclusive`/`lastDayOf` treat a timed DTEND sitting exactly
    // on local midnight as exclusive everywhere the event is displayed
    // (bucketByDay, the chips, DayPopover) and everywhere it is dragged — the
    // resize branch of `dragBody` was fixed for precisely this. The modal is the
    // one place that never consults it: ticking the box slices ten characters
    // off the timed end, so the exclusive midnight instant is reinterpreted as
    // an inclusive last day and `endOut = shiftYmd(clampedEnd, 1)` then adds
    // another day on top. Reproduced by hand on DTSTART 2026-03-02T20:00 /
    // DTEND 2026-03-03T00:00 — an event calendar.test.ts already pins as
    // rendering on 2026-03-02 only: the picker labelled "End (last day)" reads
    // 2026-03-03 the instant the box is ticked, and Save writes
    // {"start":"2026-03-02","end":"2026-03-04"}. The event now covers two days
    // here and in every other CalDAV client, after an edit the user believed
    // only changed the representation.
    const user = openCalendar([ev({ start: '2026-03-02T20:00:00', end: '2026-03-03T00:00:00' })])
    await openEvent(user)
    await user.click(screen.getByLabelText('all day'))

    // What the user is shown, before anything is saved.
    expect(screen.getByLabelText('End (last day)')).toHaveValue('2026-03-02')

    await user.click(screen.getByText('Save'))
    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    // DTEND is exclusive for an all-day event, so one day means start + 1.
    expect(patchBody()).toMatchObject({ start: '2026-03-02', end: '2026-03-03' })
  })

  // WIDENING for the same finding: a span that ends at midnight several days
  // later. The single-day case above is satisfied by any repair that subtracts
  // a day from a midnight end; this says the subtraction has to land on the
  // right day rather than collapsing the span.
  it('keeps a multi-day midnight-ending span on the days it covered', async () => {
    const user = openCalendar([ev({ start: '2026-03-02T20:00:00', end: '2026-03-05T00:00:00' })])
    await openEvent(user)
    await user.click(screen.getByLabelText('all day'))

    expect(screen.getByLabelText('End (last day)')).toHaveValue('2026-03-04')

    await user.click(screen.getByText('Save'))
    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(patchBody()).toMatchObject({ start: '2026-03-02', end: '2026-03-05' })
  })

  // Control (passes today, must keep passing). The obvious repair — subtract a
  // day whenever `allDay` is ticked — satisfies both pins above and silently
  // shortens EVERY ordinary timed event by a day. These two cases are the ones
  // that catch it, together with `all-day end conversion` in
  // CalendarView.test.tsx, which drives a genuinely all-day event whose `end`
  // state is already the inclusive day.
  it('still gives a non-midnight timed event its own single all-day day', async () => {
    const user = openCalendar([ev({ start: '2026-03-02T09:00:00', end: '2026-03-02T17:00:00' })])
    await openEvent(user)
    await user.click(screen.getByLabelText('all day'))

    expect(screen.getByLabelText('End (last day)')).toHaveValue('2026-03-02')

    await user.click(screen.getByText('Save'))
    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(patchBody()).toMatchObject({ start: '2026-03-02', end: '2026-03-03' })
  })

  // Control: ticking the box and changing your mind must give back what was
  // there. A repair that rewrites `end` state on the way in cannot pass this.
  it('gives a timed event its own times back when all-day is unticked', async () => {
    const user = openCalendar([ev({ start: '2026-03-02T20:00:00', end: '2026-03-03T00:00:00' })])
    await openEvent(user)
    const box = screen.getByLabelText('all day')
    await user.click(box)
    await user.click(box)

    expect(screen.getByLabelText('End')).toHaveValue('2026-03-03T00:00')

    await user.click(screen.getByText('Save'))
    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(patchBody()).toMatchObject({
      start: '2026-03-02T20:00', end: '2026-03-03T00:00',
    })
  })
})


// ── the dashboard ───────────────────────────────────────────────────────────

describe('2026-08-19 — the Home mini calendar', () => {
  const layout: DashboardModule[] = [{ id: 'mc', kind: 'mini_calendar', x: 0, y: 0, w: 6, h: 6 }]

  // ── AUDIT (open): HomeView.tsx:141 — the mini calendar never refetches on an
  //    SSE change, so its dots go stale while the rest of the page updates ──
  it('repaints when the account changes under an open dashboard', async () => {
    // EVIDENCE. HomeView's event fetch effect depends on `needsCal`, `from`,
    // `to` and the joined calendar-id string — all invariant under `rev`, the
    // SSE change signal. Every other data source on the same page consumes it:
    // `useTaskData` refetches on `[loadKey, rev, …]`, the scheduling modules on
    // `[rev, needsSched]`, `CalendarProvider` on `[rev, enabled]`.
    // `requestWindow` even stamps its dedupe key with `rev` specifically so a
    // bump forces a refetch — but the effect that would call it never re-runs.
    // Verified by hand: rerender at rev=1 and `api.calendars` is called twice
    // while `api.events` stays at 1, with the day button still reading the old
    // count. The user leaves Home open (which is what a dashboard is for),
    // their phone adds a meeting, Today/Overdue/Upcoming/Booking links all
    // repaint, and the mini calendar keeps yesterday's dots until the tab is
    // switched away and back.
    const { rerender } = render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <HomeView rev={0} onExpire={vi.fn()} layout={layout} onLayoutChange={vi.fn()} />
      </DataProvider>,
    )
    await waitFor(() => expect(m.events).toHaveBeenCalledTimes(1))

    // Another CalDAV client adds a meeting; Radicale's hook fires
    // /internal/changed and the SPA turns the SSE event into a `rev` bump.
    m.events.mockResolvedValue([ev({
      id: 'added', summary: 'Added elsewhere',
      start: '2026-03-10T09:00:00', end: '2026-03-10T09:30:00',
    })])
    // A rerender, not a second mount: `asked` lives in the provider above the
    // tabs, so remounting HomeView is the very thing that masks this.
    rerender(
      <DataProvider rev={1} onExpire={vi.fn()}>
        <HomeView rev={1} onExpire={vi.fn()} layout={layout} onLayoutChange={vi.fn()} />
      </DataProvider>,
    )

    // The day cell's accessible name is the whole user-visible payload here:
    // "…, 1 event" is what a screen reader reads and what the dots draw from.
    expect(await screen.findByLabelText(/1 event$/)).toBeInTheDocument()

    // …and exactly once. `requestWindow` stamps its dedupe key with `rev`, so a
    // repair that re-runs the effect must still dedupe within a rev — otherwise
    // every unrelated re-render of an open dashboard is a fresh fan-out across
    // every visible calendar, which is the request storm finding 22 closed.
    const after = m.events.mock.calls.length
    rerender(
      <DataProvider rev={1} onExpire={vi.fn()}>
        <HomeView rev={1} onExpire={vi.fn()} layout={layout} onLayoutChange={vi.fn()} />
      </DataProvider>,
    )
    await act(async () => { await Promise.resolve() })
    expect(m.events).toHaveBeenCalledTimes(after)
  })

  // ── AUDIT (open): CalendarView.tsx:242 — the SAME defect, in the tab that IS
  //    the calendar. Named in finding 42's suggested fix, pinned by nothing ──
  it('the calendar tab repaints when the account changes under it', async () => {
    // EVIDENCE. `CalendarView`'s event effect carries the identical dep array —
    // `[from, to, visibleCals.map(c => c.id).join(',')]` — every part of which
    // is invariant under an SSE change. It is masked, not absent: CalendarView
    // calls `reloadHere()` after its OWN writes, so the stale window is only
    // visible when the change came from somewhere else. That is precisely the
    // case the mini-calendar finding is about, so it is the same finding, not a
    // second one — and it is the bigger surface, because the calendar tab is
    // where a user watches for what their other clients wrote.
    //
    // Left open here on purpose, as an outcome: whether the repair is a `rev`
    // prop, a `requestWindow` dep, or a subscription, the chip has to appear.
    const { rerender } = render(<CalHarness rev={0} />)
    await screen.findByText(/^Today$/)
    await waitFor(() => expect(m.events).toHaveBeenCalledTimes(1))

    m.events.mockResolvedValue([ev({
      id: 'elsewhere', summary: 'Booked from my phone',
      start: '2026-03-10T09:00:00', end: '2026-03-10T09:30:00',
    })])
    rerender(<CalHarness rev={1} />)

    expect(await screen.findAllByTitle(/^Booked from my phone/)).not.toHaveLength(0)
  })
})

// ── the booking-link editor ─────────────────────────────────────────────────

async function openLinkEditor() {
  const user = setupUser()
  render(<SchedulingView rev={0} onExpire={vi.fn()} />)
  await user.click(await screen.findByRole('button', { name: 'New link' }))
  await screen.findByRole('dialog')
  await user.type(screen.getByPlaceholderText('30-minute intro call'), 'Intro call')
  return user
}

describe('2026-08-19 — the booking-link editor', () => {
  // ── AUDIT (open): SchedulingView.tsx:225 — a rejected save leaves the editor
  //    permanently disabled; the in-flight guard is set but never cleared ───
  it.fails('comes back to life when the save is rejected', async () => {
    // EVIDENCE. `LinkModal.save()` sets `saving = true` before calling
    // `onSave(...)`, and nothing ever sets it back. `onSave` is typed
    // `(body, token?) => void`, so the modal cannot observe the outcome;
    // `SchedulingView.save` awaits `guard(...)`, which returns undefined on any
    // failure, and deliberately leaves the modal open so the user can fix and
    // retry — but `saving` is stuck true, so `disabled={!valid || saving}` keeps
    // Create dead and the Enter handler returns at `if (!valid || saving)`. The
    // only way out is Escape, which discards title, description, timezone,
    // buffers, notice, horizon and the whole seven-day availability grid the
    // user just filled in. Reproduced by hand with a 422 from
    // `createSchedulingLink`: the dialog is still mounted, the button is
    // disabled, and a second click produces no further call. The triggers are
    // ordinary — a typo in the free-text Timezone field, overlapping
    // availability (the pin below), a dropped connection, a 502 from the tunnel.
    const user = await openLinkEditor()
    m.createSchedulingLink.mockRejectedValue(
      new HttpError(422, 'availability ranges overlap on weekday 0'))

    const create = screen.getByRole('button', { name: /create link/i })
    await user.click(create)
    await waitFor(() => expect(m.createSchedulingLink).toHaveBeenCalledTimes(1))

    expect(create).not.toBeDisabled()
    await user.click(create)                       // the retry the toast invites
    expect(m.createSchedulingLink).toHaveBeenCalledTimes(2)
  })

  // ── AUDIT (open): SchedulingView.tsx:178 — the availability editor builds
  //    overlapping windows the server 422s, and silently deletes an inverted
  //    range ────────────────────────────────────────────────────────────────
  it.fails('never submits a week the server will refuse, and never drops a range', async () => {
    // EVIDENCE. `daysToAvail` is the client's whole validation of the weekly
    // grid and implements exactly one of `parse_availability`'s two per-day
    // rules. It filters `s && e && s < e`, mirroring the server's
    // `if s >= e: raise`, but not the overlap rule four lines below it in the
    // same function — so two ranges on one day are serialized verbatim and come
    // back as 422 "availability ranges overlap on weekday 0", a raw toast the UI
    // had no way to anticipate (and, with the pin above, one that also bricks
    // the editor). The reverse half is worse: an inverted range is DROPPED, not
    // reported. Friday 17:00–09:00 — a night shift, or simply the two fields
    // entered backwards — creates a link advertising no Friday slots, and
    // reopening the editor shows Friday as "Unavailable" with no record the
    // range was ever typed.
    //
    // Both halves are built here through the UI exactly as a user would, and the
    // assertion is on what reaches the API. Refusing to submit and explaining
    // why is correct; submitting something the server accepts is correct;
    // submitting an overlap, or quietly discarding the day the user configured,
    // is not.
    const user = await openLinkEditor()

    // Monday defaults to 09:00–17:00. "+ range" appends an empty pair.
    const monday = () => document.querySelectorAll('.sched-day')[0] as HTMLElement
    await user.click(within(monday()).getByTitle('Add another range'))
    let mon = monday().querySelectorAll('input[type=time]')
    fireEvent.change(mon[2], { target: { value: '10:00' } })
    mon = monday().querySelectorAll('input[type=time]')
    fireEvent.change(mon[3], { target: { value: '12:00' } })

    // Friday: the same two fields, entered backwards.
    const friday = () => document.querySelectorAll('.sched-day')[4] as HTMLElement
    let fri = friday().querySelectorAll('input[type=time]')
    fireEvent.change(fri[0], { target: { value: '17:00' } })
    fri = friday().querySelectorAll('input[type=time]')
    fireEvent.change(fri[1], { target: { value: '09:00' } })

    await user.click(screen.getByRole('button', { name: /create link/i }))
    await act(async () => { await Promise.resolve() })

    const sent = m.createSchedulingLink.mock.calls[0]?.[0] as BookingLinkInput | undefined
    if (sent) {
      const av = sent.availability ?? {}
      const monRanges = (av['0'] ?? []).map((r) => r.split('-') as [string, string])
      const sorted = [...monRanges].sort((a, b) => a[0].localeCompare(b[0]))
      const overlapping = sorted.some((r, i) => i > 0 && r[0] < sorted[i - 1][1])
      expect(overlapping).toBe(false)
      expect(av['4'] ?? []).not.toHaveLength(0)
    }
  })
})

// ── appearance ──────────────────────────────────────────────────────────────

function openAppearance(appearance: Appearance = {}, mode: 'light' | 'dark' = 'light') {
  const onChange = vi.fn()
  render(<AppearancePanel appearance={appearance} onChange={onChange}
    mode={mode} onMode={vi.fn()} onClose={vi.fn()} />)
  const last = () => onChange.mock.calls[onChange.mock.calls.length - 1][0] as Appearance
  return { onChange, last }
}

describe('2026-08-19 — appearance', () => {
  // ── AUDIT (open): appearance.ts:324 — isColor accepts hex literals CSS
  //    rejects and non-colour functions, so a mistyped colour is stored,
  //    synced and applied while the editor reports it valid ─────────────────
  it.fails('refuses hex lengths CSS does not have, and functions that are not colours', () => {
    // EVIDENCE. The audit already closed this exact failure mode for bare words
    // ("any 3–20 letter word … stored and applied as an override that silently
    // blanks the property"), and the fix replaced that shape test with
    // membership in NAMED_COLORS. The other two branches were left as shape
    // tests. `/^#[0-9a-f]{3,8}$/i` accepts 5- and 7-digit hex, which are not
    // legal CSS <hex-color> values (only 3, 4, 6 and 8 are), and the function
    // branch only checks that every `name(` occurrence is in COLOR_FNS plus
    // paren balance — never a parse. Ran against the real module:
    // isValidToken('--bg','#12345') -> true, ('--bg','#1234567') -> true,
    // ('--accent','calc(1px)') -> true, and sanitizeTokens passes them through.
    // So `isValidToken` says fine, ColorControl never applies its `bad` class,
    // the value is written to the theme, mirrored to localStorage, PUT to the
    // account and set on the CSSOM — where `body { background: var(--bg) }`
    // becomes invalid at computed-value time and is dropped. That is the exact
    // "editor says fine, app renders as if the token had no value" state the
    // previous fix existed to eliminate.
    //
    // Paste `#0a0a0` into Surfaces → Background (a six-digit hex with one
    // character dropped) and the page paints on the browser's default canvas
    // while the panel counts it as a live override that survives a reload.
    for (const bad of ['#12345', '#1234567']) {
      expect(isValidToken('--bg', bad)).toBe(false)
    }
    for (const bad of ['calc(1px)', 'rgb(1,2,3), 0 0 0 200vmax red']) {
      expect(isValidToken('--accent', bad)).toBe(false)
    }
    // Nothing downstream catches it either — sanitizeTokens re-runs the same check.
    expect(sanitizeTokens({ '--bg': '#12345' })).toEqual({})
  })

  // A CONTROL, not a pin: this passes today and must still pass after the fix.
  // A validator that rejects `#12345` by rejecting everything would satisfy the
  // pin above and break the editor, so the real values are pinned beside it.
  it('still accepts every hex length and colour function CSS does have', () => {
    for (const ok of ['#fff', '#fff0', '#ffffff', '#ffffff80', '#FBFAF7']) {
      expect(isValidToken('--bg', ok)).toBe(true)
    }
    for (const ok of ['oklch(0.60 0.19 42)', 'rgb(20, 19, 26)', 'rgba(20, 19, 26, 0.6)',
                      'hsl(210 50% 40%)', 'color-mix(in oklch, red, blue)', 'var(--accent)',
                      'transparent', 'rebeccapurple']) {
      expect(isValidToken('--accent', ok)).toBe(true)
    }
  })

  // ── AUDIT (open): AppearancePanel.tsx:69 — shape, density and type tokens are
  //    stored per light/dark map, so nine of them revert on every theme flip ─
  it.fails('keeps a shape token when the theme flips to dark', async () => {
    // EVIDENCE. Nine of the 23 customizable tokens are not mode-specific in the
    // shipped design: --serif, --sans, --mono, --radius, --fs-scale, --gutter,
    // --row-y, --label-case and --tracking live only in SHARED_DEFAULTS and are
    // declared only in the `:root` block of tokens.css — the
    // `:root[data-theme="dark"]` block restates colours and nothing else. But
    // CustomTheme has only `light` and `dark` maps, `edit()` merges every patch
    // into `active[mode]` alone, and `resolve()`/`applyTokens()` clear all 23
    // inline properties and re-apply only the current mode's. Ran against the
    // real module: a theme with light:{'--radius':'8px', …} resolves to {} in
    // dark, and applyTokens then leaves style="". So Corners 8px, Text size 1.3
    // or Interface Georgia set in light mode are gone the moment the app flips —
    // every button, input and modal squares off, the UI shrinks, the typeface
    // changes, with the theme still selected and named — and there is no way in
    // the panel to author these once for both modes. appearance.ts's own PRESETS
    // comment names this failure ("a token it forgets would fall through to
    // Smylte's value and read as a rendering bug in one mode only") and a test
    // enforces density for presets, while user themes are left in exactly the
    // sparse state that comment warns about.
    //
    // Asserted through `resolve`, which is what the app applies, so a fix that
    // splits the patch across both maps and a fix that adds a shared bucket both
    // satisfy it. The second half is the guard rail: colours must stay
    // mode-specific, or a dark theme would be repainted in its light values.
    const { last } = openAppearance({ active: 't1', themes: [theme()] }, 'light')

    fireEvent.change(screen.getByLabelText('Corners'), { target: { value: '8' } })
    const withRadius = last()
    expect(resolve(withRadius, 'light')['--radius']).toBe('8px')
    expect(resolve(withRadius, 'dark')['--radius']).toBe('8px')

    fireEvent.change(screen.getByLabelText('Accent'), { target: { value: '#00ff00' } })
    const withAccent = last()
    expect(resolve(withAccent, 'light')['--accent']).toBe('#00ff00')
    expect(resolve(withAccent, 'dark')['--accent']).toBeUndefined()
  })
})
