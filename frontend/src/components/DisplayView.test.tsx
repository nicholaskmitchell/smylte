import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import { DisplayView } from './DisplayView'
import { api, HttpError, type DisplayFrame } from '../api'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  return { ...mod, api: { ...mod.api, publicDisplayFrame: vi.fn() } }
})

const frameMock = vi.mocked(api.publicDisplayFrame)

const CAL: DisplayFrame = {
  display: { name: 'Hallway', mode: 'calendar', palette: 'color',
    refresh_seconds: 300, rotation: 0 },
  generated_at: '2026-08-31T22:00:00.000Z',
  day: '2026-08-31',
  language: 'en',
  time_format: '24h',
  sources: [
    { id: 'work', name: 'Work', color: '#3B82F6', treatment: 'solid', initial: '' },
    { id: 'home', name: 'Home', color: '#16A34A', treatment: 'outline', initial: '' },
  ],
  calendar: {
    month: '2026-08',
    title: 'August 2026',
    weekday_names: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
    too_small_text: 'This screen is too small for a month.',
    too_small_hint: 'Set it to habits + today, or use a bigger panel.',
    weeks: [[
      { day: '2026-08-30', label: '30', in_month: true, today: false, items: [], hidden: 0 },
      { day: '2026-08-31', label: '31', in_month: true, today: true, hidden: 2,
        items: [{ text: 'Standup', time: '09:00', all_day: false, source: 'work', continued: false }] },
      { day: '2026-09-01', label: '1', in_month: false, today: false, hidden: 0,
        items: [{ text: 'Conference', time: '', all_day: true, source: 'home', continued: false }] },
    ]],
  },
}

const DAY: DisplayFrame = {
  ...CAL,
  display: { ...CAL.display, name: 'Kitchen', mode: 'habits', palette: 'eink' },
  calendar: undefined,
  habits: {
    planned: true,
    heading: 'Habits',
    day_heading: 'Today',
    habits: [
      { text: 'Stretch', done: true, kind: 'habit', source: null, estimate_minutes: 10 },
      { text: 'Read', done: false, kind: 'habit', source: null, estimate_minutes: null },
    ],
    tasks: [
      { text: 'Invoice', done: false, kind: 'task', source: 'work', estimate_minutes: null },
    ],
    habits_hidden: 0,
    tasks_hidden: 0,
    counts: { habits_done: 1, habits_total: 2, tasks_done: 0, tasks_total: 1 },
    empty_text: 'Nothing today',
    all_done_text: 'All done',
    preview_text: 'Today isn’t planned yet',
    preview_hint: 'This is what opening it would put on it.',
  },
}

const NOW: DisplayFrame = {
  ...CAL,
  display: { ...CAL.display, name: 'Desk', mode: 'now', palette: 'eink' },
  calendar: undefined,
  now: {
    planned: true,
    heading: 'Now',
    next_heading: 'Next',
    current: { text: 'Renew the insurance', kind: 'task', source: 'home',
      estimate: '1h 30m', estimate_minutes: 90 },
    next: { text: 'Email Sam', kind: 'task', source: 'work',
      estimate: '', estimate_minutes: null },
    remaining: 2,
    counts: { done: 1, total: 5 },
    empty_text: 'Nothing today',
    all_done_text: 'All done',
    preview_text: 'Today isn’t planned yet',
    preview_hint: 'This is what opening it would put on it.',
  },
}

/** A `now` frame with one block field replaced. */
const now = (over: Partial<NonNullable<DisplayFrame['now']>>): DisplayFrame =>
  ({ ...NOW, now: { ...NOW.now!, ...over } })

beforeEach(() => { frameMock.mockReset() })
afterEach(() => { vi.useRealTimers() })

describe('<DisplayView>', () => {
  it('draws the month, its chips and the overflow count', async () => {
    frameMock.mockResolvedValue(CAL)
    render(<DisplayView token="tok" />)
    expect(await screen.findByText('August 2026')).toBeInTheDocument()
    // The display's own name is on screen: a household with two panels has to
    // be able to tell which one is showing last week.
    expect(screen.getByText('Hallway')).toBeInTheDocument()
    expect(screen.getByText('Standup')).toBeInTheDocument()
    expect(screen.getByText('09:00')).toBeInTheDocument()
    // The count of what did not fit rides on the date's line rather than
    // spending an item row of its own.
    expect(screen.getByText('+2')).toBeInTheDocument()
    expect(document.querySelector('.display-cal__cell.is-today')).toBeTruthy()
    expect(document.querySelector('.display-cal__cell.is-outside')).toBeTruthy()
  })

  it('marks its headlines and micro-labels for the editorial type', async () => {
    frameMock.mockResolvedValue(CAL)
    const { container } = render(<DisplayView token="tok" />)
    await screen.findByText('August 2026')
    // These two classes ARE the editorial system on this page — serif for what
    // is looked at, tracked uppercase mono for what is scanned — and
    // `display.browser.test.tsx` measures the computed faces through them in a
    // real browser. This is the half that holds them to the real JSX, so a
    // refactor cannot drop a class and leave that suite measuring markup the
    // component no longer renders.
    expect(container.querySelector('.display-cal__title')!.className)
      .toContain('display-title')
    expect(container.querySelector('.display-cal__num')!.className)
      .toContain('display-title')
    for (const sel of ['.display-cal__name', '.display-cal__weekday', '.display-cal__more']) {
      expect(container.querySelector(sel)!.className, sel).toContain('display-label')
    }
    expect(container.querySelector('.display-cal__items .display-chip__time')).toBeInTheDocument()
  })

  it('marks the habits face the same way', async () => {
    frameMock.mockResolvedValue(DAY)
    const { container } = render(<DisplayView token="tok" />)
    await screen.findByText('Stretch')
    expect(container.querySelector('.display-day__title')!.className)
      .toContain('display-title')
    expect(container.querySelector('.display-day__tally')!.className)
      .toContain('display-title')
    expect(container.querySelector('.display-day__label')!.className)
      .toContain('display-label')
  })

  it('takes no input at all', async () => {
    frameMock.mockResolvedValue(CAL)
    const { container } = render(<DisplayView token="tok" />)
    await screen.findByText('August 2026')
    // The specification, asserted rather than assumed: a passive display that
    // could be tapped would be a bad app, and the thing most likely to tap it
    // is a cleaning cloth.
    expect(container.querySelectorAll('button, a, input, [tabindex], [role="button"]'))
      .toHaveLength(0)
  })

  it('renders a hostile event title as inert text, never as markup', async () => {
    frameMock.mockResolvedValue({
      ...CAL,
      calendar: { ...CAL.calendar!, weeks: [[{
        day: '2026-08-31', label: '31', in_month: true, today: true, hidden: 0,
        items: [{ text: '<img src=x onerror="window.__pwned=true">', time: '',
          all_day: true, source: 'work', continued: false }],
      }]] },
    })
    render(<DisplayView token="tok" />)
    // An event title can be written by any CalDAV client on these collections.
    expect(await screen.findByText('<img src=x onerror="window.__pwned=true">'))
      .toBeInTheDocument()
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined()
  })

  it('carries the calendar colour on a colour screen and drops it on eink', async () => {
    frameMock.mockResolvedValue(CAL)
    const { rerender } = render(<DisplayView token="tok" />)
    await screen.findByText('Standup')
    const mark = document.querySelector('.display-cal__items .display-chip__mark') as HTMLElement
    expect(mark.style.background).toBeTruthy()

    // On a panel one bit deep a colour is either black or invisible depending
    // on how it thresholds, so the treatment class draws the mark instead.
    frameMock.mockResolvedValue({
      ...CAL, display: { ...CAL.display, palette: 'eink' },
    })
    rerender(<DisplayView token="other" />)
    await waitFor(() => {
      expect(document.querySelector('.display--eink')).toBeTruthy()
    })
    const inkMark = document.querySelector('.display-cal__items .display-chip__mark') as HTMLElement
    expect(inkMark.style.background).toBe('')
    expect(document.querySelector('.display-cal__items .display-chip--solid')).toBeTruthy()
  })

  it('draws habits and today, with the tally counted before the hiding', async () => {
    frameMock.mockResolvedValue(DAY)
    render(<DisplayView token="tok" />)
    expect(await screen.findByText('Stretch')).toBeInTheDocument()
    expect(screen.getByText('Read')).toBeInTheDocument()
    expect(screen.getByText('Invoice')).toBeInTheDocument()
    // The score is what remains once a finished habit has left the screen.
    expect(screen.getByText('1/2')).toBeInTheDocument()
    expect(document.querySelectorAll('.display-row.is-done')).toHaveLength(1)
  })

  it('says so when the rows are a preview rather than a plan', async () => {
    frameMock.mockResolvedValue({
      ...DAY, habits: { ...DAY.habits!, planned: false },
    })
    render(<DisplayView token="tok" />)
    // Nobody has opened today. Drawing this as a plan would claim a commitment
    // the owner never made.
    expect(await screen.findByText('Today isn’t planned yet')).toBeInTheDocument()
    expect(screen.getByText('This is what opening it would put on it.'))
      .toBeInTheDocument()
  })

  it('tells an empty day from a finished one', async () => {
    frameMock.mockResolvedValue({
      ...DAY,
      habits: { ...DAY.habits!, habits: [], tasks: [],
        counts: { habits_done: 2, habits_total: 2, tasks_done: 1, tasks_total: 1 } },
    })
    const { rerender } = render(<DisplayView token="tok" />)
    expect(await screen.findByText('All done')).toBeInTheDocument()

    frameMock.mockResolvedValue({
      ...DAY,
      habits: { ...DAY.habits!, habits: [], tasks: [],
        counts: { habits_done: 0, habits_total: 0, tasks_done: 0, tasks_total: 0 } },
    })
    rerender(<DisplayView token="empty" />)
    // Only a day that HAD something has earned anything.
    expect(await screen.findByText('Nothing today')).toBeInTheDocument()
  })

  it('says the display is gone on a 404 and keeps the screen on anything else',
    async () => {
      frameMock.mockRejectedValue(new HttpError(404, 'unknown display'))
      const { unmount } = render(<DisplayView token="dead" />)
      expect(await screen.findByText(/no longer connected/i)).toBeInTheDocument()
      unmount()

      // A 500, a rate limit or a dropped packet says nothing about the display.
      // Blanking the wall over one lost response would be worse than showing a
      // slightly old month.
      frameMock.mockResolvedValueOnce(CAL)
        .mockRejectedValue(new HttpError(503, 'nope'))
      render(<DisplayView token="tok" />)
      expect(await screen.findByText('August 2026')).toBeInTheDocument()
      await act(async () => { await Promise.resolve() })
      expect(screen.getByText('August 2026')).toBeInTheDocument()
    })

  it('retries fast until something is on screen, then settles to the interval',
    async () => {
      vi.useFakeTimers()
      frameMock.mockRejectedValueOnce(new HttpError(503, 'booting'))
        .mockResolvedValue({ ...CAL, display: { ...CAL.display, refresh_seconds: 900 } })
      render(<DisplayView token="tok" />)
      await act(async () => { await Promise.resolve() })
      expect(frameMock).toHaveBeenCalledTimes(1)
      // A panel boots when the room's light switch does, often before the wifi
      // has an address — so the first fetch is the one most likely to fail, and
      // waiting out a 15-minute interval would be 15 minutes of blank wall.
      await act(async () => { vi.advanceTimersByTime(15_000) })
      expect(frameMock).toHaveBeenCalledTimes(2)
      // With a frame on screen there is nothing urgent left.
      await act(async () => { vi.advanceTimersByTime(15_000) })
      expect(frameMock).toHaveBeenCalledTimes(2)
      await act(async () => { vi.advanceTimersByTime(885_000) })
      expect(frameMock).toHaveBeenCalledTimes(3)
    })

  it('still draws a month on a browser with no ResizeObserver', async () => {
    // Old tablets and cheap kiosk webviews are exactly the hardware this page
    // is for, and `new ResizeObserver` on a browser without one throws inside
    // the layout effect — which unmounts the tree and leaves the panel BLANK.
    // jsdom has none either, which is what surfaced it.
    frameMock.mockResolvedValue(CAL)
    render(<DisplayView token="tok" />)
    expect(await screen.findByText('August 2026')).toBeInTheDocument()
    expect(screen.getByText('Standup')).toBeInTheDocument()
  })

  it('polls at the interval the frame asks for', async () => {
    vi.useFakeTimers()
    frameMock.mockResolvedValue({
      ...CAL, display: { ...CAL.display, refresh_seconds: 60 },
    })
    render(<DisplayView token="tok" />)
    await act(async () => { await Promise.resolve() })
    expect(frameMock).toHaveBeenCalledTimes(1)
    // The cadence comes from the frame, not from a constant in the page, so
    // changing it in Settings reaches the panel without touching the device.
    await act(async () => { vi.advanceTimersByTime(60_000) })
    expect(frameMock).toHaveBeenCalledTimes(2)
    await act(async () => { vi.advanceTimersByTime(60_000) })
    expect(frameMock).toHaveBeenCalledTimes(3)
  })

  it('measures staleness against the cadence, not against a flat 20 minutes',
    async () => {
      // Settings offers "Every hour". Against a flat threshold a display on
      // that cadence reported itself stale for forty minutes out of every
      // healthy hour — which teaches the one person who reads the strip to
      // stop believing it.
      vi.useFakeTimers()
      frameMock.mockResolvedValue({
        ...CAL, display: { ...CAL.display, refresh_seconds: 3600 },
      })
      render(<DisplayView token="tok" />)
      await act(async () => { await Promise.resolve() })
      // Half an hour in, one poll has not even come due yet.
      await act(async () => { vi.advanceTimersByTime(30 * 60_000) })
      expect(screen.queryByText('Not updated recently')).toBeNull()

      // And it still says so eventually: silence past several polls is real.
      frameMock.mockRejectedValue(new Error('offline'))
      await act(async () => { vi.advanceTimersByTime(3 * 60 * 60_000) })
      expect(screen.getByText('Not updated recently')).toBeInTheDocument()
    })

  it('says how many rows the frame itself had to drop', async () => {
    // The habits-mode twin of a calendar cell's "+N". Without it a section
    // showed the first twenty of forty and implied that was the day.
    frameMock.mockResolvedValue({
      ...DAY,
      habits: { ...DAY.habits!, habits_hidden: 3, tasks_hidden: 0 },
    })
    render(<DisplayView token="tok" />)
    await screen.findByText('Stretch')
    expect(screen.getByText('+3')).toBeInTheDocument()
  })
})

describe('<DisplayView> — the rolling face', () => {
  it('draws the one thing you are on, the one after it, and the count', async () => {
    frameMock.mockResolvedValue(NOW)
    render(<DisplayView token="tok" />)
    expect(await screen.findByText('Renew the insurance')).toBeInTheDocument()
    expect(screen.getByText('Now')).toBeInTheDocument()
    expect(screen.getByText('Next')).toBeInTheDocument()
    expect(screen.getByText('Email Sam')).toBeInTheDocument()
    expect(screen.getByText('1h 30m')).toBeInTheDocument()
    // The count is what is behind the next item — the only part of the day the
    // reader cannot see. Under jsdom every box is 0×0 so `fitNow` measures
    // nothing and drops nothing, which is exactly the "everything fitted" case.
    expect(screen.getByText('+2')).toBeInTheDocument()
    // The score, and on this face it is the only thing that remembers the
    // finished rows: they never appear on it at all.
    expect(screen.getByText('1/5')).toBeInTheDocument()
  })

  it('never draws a row that is already done', async () => {
    // The cursor is the frame's job (`build_now` sends only the two open rows),
    // and this pins the face to it: nothing here filters, so a done row
    // reaching the block would be drawn as the thing you are on.
    frameMock.mockResolvedValue(NOW)
    render(<DisplayView token="tok" />)
    await screen.findByText('Renew the insurance')
    expect(document.querySelector('.display-row.is-done')).toBeNull()
  })

  it('tells a finished day from an empty one', async () => {
    frameMock.mockResolvedValue(now({
      current: null, next: null, remaining: 0, counts: { done: 5, total: 5 } }))
    const { unmount } = render(<DisplayView token="tok" />)
    expect(await screen.findByText('All done')).toBeInTheDocument()
    // No eyebrow: nothing is "now", and "Now / All done" reads as a task
    // called All done.
    expect(document.querySelector('.display-now__eyebrow')).toBeNull()
    unmount()

    frameMock.mockResolvedValue(now({
      current: null, next: null, remaining: 0, counts: { done: 0, total: 0 } }))
    render(<DisplayView token="tok" />)
    expect(await screen.findByText('Nothing today')).toBeInTheDocument()
  })

  it('says so when the day is a preview nobody opened', async () => {
    frameMock.mockResolvedValue(now({ planned: false }))
    render(<DisplayView token="tok" />)
    // It matters more here than on any other face: "Now: fix the boiler" on a
    // day nobody opened reads as a commitment the owner has not made.
    expect(await screen.findByText('Today isn’t planned yet')).toBeInTheDocument()
    expect(screen.getByText('This is what opening it would put on it.'))
      .toBeInTheDocument()
  })

  it('marks a habit differently from a task', async () => {
    frameMock.mockResolvedValue(now({
      current: { text: 'Stretch', kind: 'habit', source: null, estimate: '',
        estimate_minutes: null } }))
    render(<DisplayView token="tok" />)
    await screen.findByText('Stretch')
    expect(document.querySelector('.display-now__eyebrow .display-row__ring'))
      .toBeTruthy()
    expect(document.querySelector('.display-now__eyebrow .display-row__box'))
      .toBeNull()
  })

  it('marks its headline and micro-labels for the editorial type', async () => {
    frameMock.mockResolvedValue(NOW)
    const { container } = render(<DisplayView token="tok" />)
    await screen.findByText('Renew the insurance')
    // Holds `display.browser.test.tsx`'s markup harness to the real JSX, the
    // same job the two assertions above it do for the other faces.
    for (const sel of ['.display-now__title', '.display-now__name', '.display-now__tally']) {
      expect(container.querySelector(sel)!.className, sel).toContain('display-title')
    }
    for (const sel of ['.display-now__eyebrow', '.display-now__est',
                       '.display-now__next-label', '.display-now__more']) {
      expect(container.querySelector(sel)!.className, sel).toContain('display-label')
    }
    // The box the clamp lives in — without it `-webkit-line-clamp` is
    // blockified away and the last line is cut through its letters.
    expect(container.querySelector('.display-now__titlebox .display-now__title'))
      .toBeTruthy()
  })

  it('renders a hostile title as inert text, never as markup', async () => {
    frameMock.mockResolvedValue(now({
      current: { text: '<img src=x onerror="window.__pwned=true">', kind: 'task',
        source: null, estimate: '', estimate_minutes: null } }))
    render(<DisplayView token="tok" />)
    // A task title can be written by any CalDAV client on these collections.
    expect(await screen.findByText('<img src=x onerror="window.__pwned=true">'))
      .toBeInTheDocument()
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined()
  })

  it('takes no input, exactly like the other two faces', async () => {
    frameMock.mockResolvedValue(NOW)
    const { container } = render(<DisplayView token="tok" />)
    await screen.findByText('Renew the insurance')
    expect(container.querySelectorAll('button, a, input, [tabindex], [role="button"]'))
      .toHaveLength(0)
  })
})
