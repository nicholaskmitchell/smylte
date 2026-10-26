import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { SharePage } from './SharePage'
import {
  api, AuthError, HttpError,
  type ShareEvent, type ShareFocus, type ShareList, type ShareRow, type ShareView,
} from '../api'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  return { ...mod, api: { ...mod.api, publicShareView: vi.fn() } }
})

const viewMock = vi.mocked(api.publicShareView)

// 10:00 in New York, the zone the unit project pins. Far from a DST change, so
// no test below is about the clocks going back.
const T0 = new Date('2026-10-26T14:00:00.000Z')
const iso = (seconds: number) => new Date(T0.getTime() + seconds * 1000).toISOString()

const fresh = (body: ShareView, etag = 'e1') => ({ status: 'fresh' as const, body, etag })

const row = (over: Partial<ShareRow> & { key: string, title: string }): ShareRow => ({
  done: false, list: 0, due: null, all_day: false, private: false, ...over,
})
const ROWS: ShareRow[] = [
  row({ key: 'k1', title: 'Draft the memo' }),
  row({ key: 'k2', title: 'Call printer' }),
  row({ key: 'k3', title: 'Email Sam', done: true }),
]
const LIST: ShareList = {
  name: 'Work', color: '#3A7BD5', more: 0,
  tasks: [{ title: 'Quarterly report', due: null, all_day: false, depth: 0, private: false }],
}
const BASE: ShareView = {
  v: 1, generated_at: T0.toISOString(), poll_seconds: 30, day: '2026-10-26', days: 7,
  focus: null, lists: [], calendars: [], events: [], events_more: 0,
}
const ev = (over: Partial<ShareEvent> & { title: string, start: string }): ShareEvent => ({
  end: null, all_day: false, calendar: 0, private: false, ...over,
})
const CAL = [{ name: 'Personal', color: '#D94F70' }]

/** A view with a focus session in it; `over` replaces fields of the session. */
function focused(over: Partial<ShareFocus> = {}, view: Partial<ShareView> = {}): ShareView {
  return {
    ...BASE, poll_seconds: 15, lists: [LIST], ...view,
    focus: {
      state: 'focusing', phase: 'focus', phase_length_s: 1500, ends_at: iso(300),
      remaining_s: null, today: { rows: ROWS, now: 'k1', next: ['k2'] }, ...over,
    },
  }
}

/** Let the pending fetch settle and run whatever timers fall in `ms`. */
const settle = (ms = 0) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state })
  act(() => { document.dispatchEvent(new Event('visibilitychange')) })
}

const clock = () => document.querySelector('.share-presence__clock')?.textContent

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(T0)
  viewMock.mockReset()
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  // Back to the prototype's getter, so no test leaves the tab hidden.
  delete (document as unknown as Record<string, unknown>).visibilityState
  delete (navigator as unknown as Record<string, unknown>).wakeLock
  document.title = ''
})

describe('<SharePage> — the presence card', () => {
  it('counts down from ends_at on the server’s clock, whatever the device says', async () => {
    // A tablet on a kitchen wall can be hours off. The page measures the gap
    // between `generated_at` and the moment the answer arrived, so a device
    // three hours ahead still reads five minutes left, not "interval over".
    vi.setSystemTime(new Date(T0.getTime() + 3 * 3_600_000))
    viewMock.mockResolvedValue(fresh(focused()))
    render(<SharePage token="tok" />)
    await settle()
    expect(clock()).toBe('5:00')
    expect(screen.getByText('Focusing')).toBeInTheDocument()
    await settle(1_000)
    expect(clock()).toBe('4:59')
  })

  it('holds a paused clock still', async () => {
    viewMock.mockResolvedValue(fresh(focused({ state: 'paused', ends_at: null, remaining_s: 600 })))
    render(<SharePage token="tok" />)
    await settle()
    expect(screen.getByText('Paused')).toBeInTheDocument()
    expect(clock()).toBe('10:00')
    await settle(5 * 60_000)
    expect(clock()).toBe('10:00')
  })

  it('names a long break as one', async () => {
    viewMock.mockResolvedValue(fresh(focused({ state: 'break', phase: 'long_break' })))
    render(<SharePage token="tok" />)
    await settle()
    expect(screen.getByText('On a long break')).toBeInTheDocument()
    expect(screen.queryByText('On a break')).toBeNull()
  })

  it('turns to "interval over" the moment ends_at passes, with no fetch', async () => {
    // `poll_seconds` is long so the only fetch that could be due is the one
    // aimed at two seconds past the end.
    viewMock.mockResolvedValue(fresh(focused({}, { poll_seconds: 600 })))
    render(<SharePage token="tok" />)
    await settle()
    expect(viewMock).toHaveBeenCalledTimes(1)
    await settle(301_000)
    expect(screen.getByText('Interval over')).toBeInTheDocument()
    expect(document.querySelector('.share-presence__clock')).toBeNull()
    expect(viewMock).toHaveBeenCalledTimes(1)
    // And the extra fetch lands at ends_at + 2s, ahead of the 600s poll.
    await settle(2_000)
    expect(viewMock).toHaveBeenCalledTimes(2)
  })

  it('says "break over" after a break and "interval over" after a focus', async () => {
    viewMock.mockResolvedValue(fresh(focused({ state: 'between', phase: 'break', ends_at: null })))
    render(<SharePage token="tok" />)
    await settle()
    expect(screen.getByText('Break over')).toBeInTheDocument()
  })

  it('shows what they are working on and what comes then', async () => {
    viewMock.mockResolvedValue(fresh(focused()))
    render(<SharePage token="tok" />)
    await settle()
    expect(screen.getByText('Working on')).toBeInTheDocument()
    expect(document.querySelector('.share-now__title')?.textContent).toBe('Draft the memo')
    expect(document.querySelector('.share-then')?.textContent).toContain('Call printer')
    expect(document.querySelector('.share-row.is-now')?.textContent).toContain('Draft the memo')
  })

  it('shows the clock and no title when the session is on something not shared', async () => {
    viewMock.mockResolvedValue(fresh(focused({ today: { rows: ROWS, now: null, next: [] } })))
    render(<SharePage token="tok" />)
    await settle()
    expect(clock()).toBe('5:00')
    expect(document.querySelector('.share-now__title')).toBeNull()
    expect(screen.queryByText('Working on')).toBeNull()
  })

  it('says what they are in the middle of when idle during an event', async () => {
    viewMock.mockResolvedValue(fresh(focused(
      { state: 'idle', phase: null, ends_at: null, today: { rows: ROWS, now: null, next: ['k1', 'k2'] } },
      { calendars: CAL, events: [ev({ title: 'Standup', start: iso(-1800), end: iso(1800) })] },
    )))
    render(<SharePage token="tok" />)
    await settle()
    expect(screen.getByText('Not focusing right now')).toBeInTheDocument()
    expect(screen.getByText(/In “Standup” until 10:30/)).toBeInTheDocument()
    // The same event is under way in the agenda, marked.
    expect(document.querySelector('.share-ev.is-now')).toBeTruthy()
  })

  it('lists what is up next when idle and nothing is under way', async () => {
    viewMock.mockResolvedValue(fresh(focused(
      { state: 'idle', phase: null, ends_at: null, today: { rows: ROWS, now: null, next: ['k1', 'k2'] } },
    )))
    render(<SharePage token="tok" />)
    await settle()
    const then = document.querySelector('.share-then')!
    expect(then.textContent).toContain('Up next')
    expect(then.textContent).toContain('Draft the memo')
    expect(then.textContent).toContain('Call printer')
  })

  it('counts today’s rows and marks the finished ones', async () => {
    viewMock.mockResolvedValue(fresh(focused()))
    render(<SharePage token="tok" />)
    await settle()
    expect(screen.getByText('1 of 3 done')).toBeInTheDocument()
    expect(document.querySelectorAll('.share-row.is-done')).toHaveLength(1)
    expect(document.querySelector('.share-row.is-done')?.textContent).toContain('Email Sam')
  })

  it('flashes a row that was ticked since the last answer', async () => {
    viewMock
      .mockResolvedValueOnce(fresh(focused()))
      .mockResolvedValue(fresh(focused({
        today: { rows: [ROWS[0], ROWS[1], { ...ROWS[1], key: 'k2', done: true }], now: 'k1', next: [] },
      }), 'e2'))
    render(<SharePage token="tok" />)
    await settle()
    expect(document.querySelector('.just-done')).toBeNull()
    await settle(15_000)
    expect(document.querySelector('.just-done')?.textContent).toContain('Call printer')
    await settle(1_500)
    expect(document.querySelector('.just-done')).toBeNull()
  })
})

describe('<SharePage> — polling', () => {
  it('waits poll_seconds between fetches', async () => {
    viewMock.mockResolvedValue(fresh({ ...BASE, poll_seconds: 15, lists: [LIST] }))
    render(<SharePage token="tok" />)
    await settle()
    expect(viewMock).toHaveBeenCalledTimes(1)
    await settle(14_900)
    expect(viewMock).toHaveBeenCalledTimes(1)
    await settle(100)
    expect(viewMock).toHaveBeenCalledTimes(2)
  })

  it('resends the etag, and keeps the content on "unchanged"', async () => {
    viewMock
      .mockResolvedValueOnce(fresh({ ...BASE, lists: [LIST] }, 'W/"abc"'))
      .mockResolvedValue({ status: 'unchanged' })
    render(<SharePage token="tok" />)
    await settle()
    await settle(30_000)
    expect(viewMock).toHaveBeenCalledTimes(2)
    expect(viewMock.mock.calls[0][1]).toBeNull()
    expect(viewMock.mock.calls[1][1]).toBe('W/"abc"')
    expect(screen.getByText('Work')).toBeInTheDocument()
  })

  it('stops polling in a hidden tab and fetches again on coming back', async () => {
    viewMock.mockResolvedValue(fresh({ ...BASE, lists: [LIST] }))
    render(<SharePage token="tok" />)
    await settle()
    setVisibility('hidden')
    await settle(5 * 60_000)
    expect(viewMock).toHaveBeenCalledTimes(1)
    setVisibility('visible')
    await settle()
    expect(viewMock).toHaveBeenCalledTimes(2)
  })

  it('does not refetch on a wake-up that follows a fetch by a moment', async () => {
    viewMock.mockResolvedValue(fresh({ ...BASE, lists: [LIST] }))
    render(<SharePage token="tok" />)
    await settle()
    setVisibility('hidden')
    await settle(1_000)
    setVisibility('visible')
    await settle()
    expect(viewMock).toHaveBeenCalledTimes(1)
  })

  it('keeps what it has on a 5xx, and says so once the silence is long', async () => {
    viewMock
      .mockResolvedValueOnce(fresh({ ...BASE, lists: [LIST] }))
      .mockRejectedValue(new HttpError(503, 'down'))
    render(<SharePage token="tok" />)
    await settle()
    await settle(60_000)
    expect(screen.getByText('Work')).toBeInTheDocument()
    expect(screen.queryByText('Not updated recently')).toBeNull()
    await settle(4 * 60_000)
    expect(screen.getByText('Work')).toBeInTheDocument()
    expect(screen.getByText('Not updated recently')).toBeInTheDocument()
  })

  it('shows "unavailable" with Try again when nothing has loaded, for a proxy or a 500', async () => {
    viewMock.mockRejectedValueOnce(new AuthError('sign in'))
    render(<SharePage token="tok" />)
    await settle()
    expect(screen.getByText('Couldn’t load this page just now.')).toBeInTheDocument()
    viewMock.mockRejectedValueOnce(new HttpError(500, 'share unavailable'))
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await settle()
    expect(screen.getByText('Couldn’t load this page just now.')).toBeInTheDocument()
    viewMock.mockResolvedValue(fresh({ ...BASE, lists: [LIST] }))
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await settle()
    expect(screen.getByText('Work')).toBeInTheDocument()
    expect(screen.queryByText('Couldn’t load this page just now.')).toBeNull()
  })

  it('backs off while it is failing', async () => {
    viewMock.mockRejectedValue(new HttpError(503, 'down'))
    render(<SharePage token="tok" />)
    await settle()
    expect(viewMock).toHaveBeenCalledTimes(1)
    await settle(5_000)
    expect(viewMock).toHaveBeenCalledTimes(2)
    await settle(9_900)
    expect(viewMock).toHaveBeenCalledTimes(2)
    await settle(100)
    expect(viewMock).toHaveBeenCalledTimes(3)
  })
})

describe('<SharePage> — a link that stops working', () => {
  const goneAfterOne = async () => {
    viewMock
      .mockResolvedValueOnce(fresh({ ...BASE, lists: [{ ...LIST, name: 'Secret plans' }] }))
      .mockRejectedValue(new HttpError(404, 'unknown share'))
    render(<SharePage token="tok" />)
    await settle()
    expect(screen.getByText('Secret plans')).toBeInTheDocument()
    await settle(30_000)
  }

  it('wipes the page on a 404, stops polling, and asks again only on the button', async () => {
    await goneAfterOne()
    expect(viewMock).toHaveBeenCalledTimes(2)
    expect(screen.getByText('This page isn’t available right now.')).toBeInTheDocument()
    expect(screen.getByText('Reload later, or ask the person who shared it.')).toBeInTheDocument()
    // The data is gone from the DOM, not hidden.
    expect(screen.queryByText('Secret plans')).toBeNull()
    expect(document.body.textContent).not.toContain('Secret plans')
    await settle(10 * 60_000)
    expect(viewMock).toHaveBeenCalledTimes(2)
    fireEvent.click(screen.getByRole('button', { name: 'Check again' }))
    await settle()
    expect(viewMock).toHaveBeenCalledTimes(3)
    await settle(10 * 60_000)
    expect(viewMock).toHaveBeenCalledTimes(3)
  })

  it('ignores the tab coming back, the network returning and a restored page', async () => {
    // A revoked page that quietly resumed whenever someone switched tabs would
    // be asking the server about a link it was told is dead. Only the button
    // asks again.
    await goneAfterOne()
    // Long enough since the last attempt that a live page WOULD refetch.
    await settle(10_000)
    setVisibility('hidden')
    setVisibility('visible')
    act(() => { window.dispatchEvent(new Event('online')) })
    const shown = new Event('pageshow')
    Object.defineProperty(shown, 'persisted', { value: true })
    act(() => { window.dispatchEvent(shown) })
    await settle(60_000)
    expect(viewMock).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('button', { name: 'Check again' })).toBeInTheDocument()
  })

  it('comes back when the button finds the link working again', async () => {
    await goneAfterOne()
    viewMock.mockResolvedValue(fresh({ ...BASE, lists: [{ ...LIST, name: 'Back again' }] }))
    fireEvent.click(screen.getByRole('button', { name: 'Check again' }))
    await settle()
    expect(screen.getByText('Back again')).toBeInTheDocument()
    await settle(30_000)
    expect(viewMock).toHaveBeenCalledTimes(4)
  })
})

describe('<SharePage> — what it draws', () => {
  it('draws hostile titles as inert text and puts no link or image in the body', async () => {
    const evil = '<img src=x onerror="window.__pwned=true">'
    viewMock.mockResolvedValue(fresh({
      ...BASE, calendars: CAL,
      lists: [{ ...LIST, name: evil, tasks: [{ title: evil, due: null, all_day: false, depth: 0, private: false }] }],
      events: [ev({ title: evil, start: iso(3600), end: iso(7200) })],
    }))
    const { container } = render(<SharePage token="tok" />)
    await settle()
    expect(screen.getAllByText(evil).length).toBeGreaterThan(1)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('a[href]')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined()
  })

  it('shows only "nothing is shared" for an empty share', async () => {
    viewMock.mockResolvedValue(fresh(BASE))
    render(<SharePage token="tok" />)
    await settle()
    expect(screen.getByText('Nothing is shared here yet.')).toBeInTheDocument()
    expect(document.querySelectorAll('.share-card')).toHaveLength(1)
  })

  it('speaks the viewer’s language, not an account’s', async () => {
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['de-DE'])
    viewMock.mockResolvedValue(fresh(BASE))
    render(<SharePage token="tok" />)
    await settle()
    expect(screen.getByText('Mit dir geteilt')).toBeInTheDocument()
    expect(screen.getByText('Hier ist noch nichts geteilt.')).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('de')
  })

  it('puts the countdown in the tab title and never any owner text', async () => {
    viewMock.mockResolvedValue(fresh(focused({}, { lists: [{ ...LIST, name: 'Secret plans' }] })))
    render(<SharePage token="tok" />)
    await settle()
    expect(document.title).toBe('5:00 · Shared view · Smylte')
    expect(document.title).not.toContain('Draft the memo')
    expect(document.title).not.toContain('Secret plans')
  })

  it('writes nothing to storage', async () => {
    const set = vi.spyOn(Storage.prototype, 'setItem')
    viewMock.mockResolvedValue(fresh(focused()))
    render(<SharePage token="tok" />)
    await settle(60_000)
    expect(set).not.toHaveBeenCalled()
  })

  it('offers to keep the screen on only where the browser can', async () => {
    viewMock.mockResolvedValue(fresh(BASE))
    const first = render(<SharePage token="tok" />)
    await settle()
    expect(screen.queryByRole('button', { name: 'Keep screen on' })).toBeNull()
    first.unmount()

    const release = vi.fn()
    const request = vi.fn().mockResolvedValue({ release, released: false })
    Object.defineProperty(navigator, 'wakeLock', { configurable: true, value: { request } })
    render(<SharePage token="tok" />)
    await settle()
    fireEvent.click(screen.getByRole('button', { name: 'Keep screen on' }))
    await settle()
    expect(request).toHaveBeenCalledWith('screen')
    expect(screen.getByRole('button', { name: 'Screen stays on' })).toBeInTheDocument()
  })
})

describe('<SharePage> — private items', () => {
  it('shows Busy for a private event, task and row, and keeps their times', async () => {
    viewMock.mockResolvedValue(fresh(focused({
      state: 'idle', phase: null, ends_at: null,
      today: {
        rows: [row({ key: 'p1', title: '', private: true, due: iso(7200) }),
          row({ key: 'u1', title: '' })],
        now: null, next: [],
      },
    }, {
      calendars: CAL,
      events: [ev({ title: '', private: true, start: iso(3600), end: iso(5400) })],
      lists: [{
        ...LIST, tasks: [
          { title: '', due: iso(7200), all_day: false, depth: 0, private: true },
          { title: '', due: null, all_day: false, depth: 0, private: false },
        ],
      }],
    })))
    render(<SharePage token="tok" />)
    await settle()
    const ev0 = document.querySelector('.share-ev')!
    expect(ev0.querySelector('.share-ev__title')?.textContent).toBe('Busy')
    expect(ev0.querySelector('.share-ev__time')?.textContent).toBe('11:00 AM–11:30 AM')
    const tasks = [...document.querySelectorAll('.share-task')]
    expect(tasks[0].querySelector('.share-task__text')?.textContent).toBe('Busy')
    expect(tasks[0].querySelector('.share-task__due')?.textContent).toBe('Due Today 12:00 PM')
    // An untitled task that is not private is a different thing to say.
    expect(tasks[1].querySelector('.share-task__text')?.textContent).toBe('(no title)')
    const rows = [...document.querySelectorAll('.share-row')]
    expect(rows[0].querySelector('.share-row__text')?.textContent).toBe('Busy')
    expect(rows[1].querySelector('.share-row__text')?.textContent).toBe('(no title)')
  })

  it('reads a private "now" as Busy', async () => {
    viewMock.mockResolvedValue(fresh(focused({
      today: { rows: [row({ key: 'p1', title: '', private: true })], now: 'p1', next: [] },
    })))
    render(<SharePage token="tok" />)
    await settle()
    expect(document.querySelector('.share-now__title')?.textContent).toBe('Busy')
  })
})

describe('<SharePage> — the agenda', () => {
  it('draws the week from the viewer’s own today and every day of a short horizon', async () => {
    viewMock.mockResolvedValue(fresh({
      ...BASE, calendars: CAL,
      events: [
        ev({ title: 'Standup', start: iso(3600), end: iso(5400) }),
        ev({ title: 'Conference', start: '2026-10-27', end: '2026-10-29', all_day: true }),
      ],
    }))
    render(<SharePage token="tok" />)
    await settle()
    expect(document.querySelectorAll('.share-day')).toHaveLength(7)
    const labels = [...document.querySelectorAll('.share-day__label')].map((h) => h.textContent)
    expect(labels.slice(0, 3)).toEqual(['Today', 'Tomorrow', 'Wednesday, October 28'])
    // A two-day all-day span (exclusive end) is on both of its days, once each.
    expect(screen.getAllByText('Conference')).toHaveLength(2)
    expect(screen.getAllByText('All day')).toHaveLength(2)
  })

  it('leaves out the empty days past tomorrow on a long horizon', async () => {
    viewMock.mockResolvedValue(fresh({
      ...BASE, days: 28, calendars: CAL,
      events: [ev({ title: 'Dentist', start: '2026-11-05T15:00:00.000Z', end: '2026-11-05T16:00:00.000Z' })],
    }))
    render(<SharePage token="tok" />)
    await settle()
    const labels = [...document.querySelectorAll('.share-day__label')].map((h) => h.textContent)
    expect(labels).toEqual(['Today', 'Tomorrow', 'Thursday, November 5'])
    expect(screen.getByText('Dentist')).toBeInTheDocument()
  })

  it('draws one day for a one-day horizon', async () => {
    viewMock.mockResolvedValue(fresh({
      ...BASE, days: 1, calendars: CAL,
      events: [ev({ title: 'Standup', start: iso(3600), end: iso(5400) })],
    }))
    render(<SharePage token="tok" />)
    await settle()
    expect(document.querySelectorAll('.share-day')).toHaveLength(1)
  })

  it.each([1, 7, 28])('says so when %i days hold nothing', async (days) => {
    viewMock.mockResolvedValue(fresh({ ...BASE, days, calendars: CAL }))
    render(<SharePage token="tok" />)
    await settle()
    expect(screen.getByText('Nothing on the calendar.')).toBeInTheDocument()
    expect(document.querySelector('.share-day')).toBeNull()
  })

  it('says how many events did not fit', async () => {
    viewMock.mockResolvedValue(fresh({
      ...BASE, calendars: CAL, events_more: 3,
      events: [ev({ title: 'Standup', start: iso(3600), end: iso(5400) })],
    }))
    render(<SharePage token="tok" />)
    await settle()
    expect(screen.getByText('+3 more')).toBeInTheDocument()
  })

  it('draws the calendar’s colour on the dot only when it has one', async () => {
    viewMock.mockResolvedValue(fresh({
      ...BASE, calendars: [{ name: 'A', color: '#D94F70' }, { name: 'B', color: null }],
      events: [
        ev({ title: 'One', start: iso(3600), end: iso(5400), calendar: 0 }),
        ev({ title: 'Two', start: iso(7200), end: iso(9000), calendar: 1 }),
      ],
    }))
    render(<SharePage token="tok" />)
    await settle()
    const dots = [...document.querySelectorAll<HTMLElement>('.share-ev__dot')]
    expect(dots[0].style.background).toBeTruthy()
    expect(dots[1].style.background).toBe('')
  })
})

describe('<SharePage> — the lists', () => {
  it('opens a single short list and folds a long one', async () => {
    const many: ShareList = {
      ...LIST, tasks: Array.from({ length: 9 }, (_, i) => (
        { title: `Task ${i}`, due: null, all_day: false, depth: i % 4, private: false })),
    }
    viewMock.mockResolvedValue(fresh({ ...BASE, lists: [LIST] }))
    const first = render(<SharePage token="tok" />)
    await settle()
    expect(document.querySelector<HTMLDetailsElement>('details.share-list')!.open).toBe(true)
    first.unmount()

    viewMock.mockResolvedValue(fresh({ ...BASE, lists: [many] }))
    render(<SharePage token="tok" />)
    await settle()
    expect(document.querySelector<HTMLDetailsElement>('details.share-list')!.open).toBe(false)
    expect(document.querySelector('.share-task[data-depth="3"]')).toBeTruthy()
  })

  it('marks an overdue task, and says what is empty', async () => {
    viewMock.mockResolvedValue(fresh({
      ...BASE,
      lists: [
        { ...LIST, tasks: [
          { title: 'Late', due: '2026-10-20', all_day: true, depth: 0, private: false },
          { title: 'Soon', due: '2026-10-27', all_day: true, depth: 0, private: false },
        ], more: 2 },
        { name: '', color: null, tasks: [], more: 0 },
      ],
    }))
    render(<SharePage token="tok" />)
    await settle()
    const due = [...document.querySelectorAll('.share-task__due')]
    expect(due[0].className).toContain('is-late')
    expect(due[0].textContent).toBe('Due Oct 20')
    expect(due[1].className).not.toContain('is-late')
    expect(due[1].textContent).toBe('Due Tomorrow')
    expect(screen.getByText('+2 more')).toBeInTheDocument()
    expect(screen.getByText('Untitled list')).toBeInTheDocument()
    expect(screen.getByText('No open tasks.')).toBeInTheDocument()
  })
})
