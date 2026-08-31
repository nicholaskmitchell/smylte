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
    counts: { habits_done: 1, habits_total: 2, tasks_done: 0, tasks_total: 1 },
    empty_text: 'Nothing today',
    all_done_text: 'All done',
    preview_text: 'Today isn’t planned yet',
    preview_hint: 'This is what opening it would put on it.',
  },
}

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
    const mark = document.querySelector('.display-chip__mark') as HTMLElement
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
    const inkMark = document.querySelector('.display-chip__mark') as HTMLElement
    expect(inkMark.style.background).toBe('')
    expect(document.querySelector('.display-chip--solid')).toBeTruthy()
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
})
