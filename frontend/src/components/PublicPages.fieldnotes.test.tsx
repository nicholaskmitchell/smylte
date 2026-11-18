// The booking page, the share page and Display mode's bar under Field notes
// (`data-surface="app"`): the hints and tooltips are not rendered, the share
// rows carry the drawn mark and strike, and the bar's three faces are a
// segmented control. Every one of these is the preset's markup when the
// attribute is absent, so each test also looks at that side.
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BookingPage } from './BookingPage'
import { SharePage } from './SharePage'
import { DisplayModeFrame } from './DisplayModeFrame'
import { api, HttpError, type DisplayFrame, type PublicBookingInfo, type ShareView } from '../api'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  return {
    ...mod,
    api: {
      ...mod.api,
      publicBookingInfo: vi.fn(), publicBook: vi.fn(), publicShareView: vi.fn(), displayPreview: vi.fn(),
    },
  }
})

const infoMock = vi.mocked(api.publicBookingInfo)
const viewMock = vi.mocked(api.publicShareView)
const previewMock = vi.mocked(api.displayPreview)

const setSurface = (on: boolean) => {
  if (on) document.documentElement.setAttribute('data-surface', 'app')
  else document.documentElement.removeAttribute('data-surface')
}

beforeEach(() => {
  infoMock.mockReset()
  viewMock.mockReset()
  previewMock.mockReset()
})
afterEach(() => {
  cleanup()
  document.documentElement.removeAttribute('data-surface')
  delete (navigator as unknown as Record<string, unknown>).wakeLock
})

// ── the booking page ──────────────────────────────────────────────────────

const INFO: PublicBookingInfo = {
  token: 'tok', title: 'Intro call', description: 'Say hi', duration_minutes: 30,
  timezone: 'UTC',
  slots: [
    { start: '2026-07-20T10:00:00+00:00', end: '2026-07-20T10:30:00+00:00' },
  ],
  busy: [{ start: '2026-07-20T12:00:00+00:00', end: '2026-07-20T13:00:00+00:00' }],
}

describe('<BookingPage> under Field notes', () => {
  it.each([
    ['not found', new HttpError(404, 'unknown booking link'), 'Ask the person who sent it for a new link.'],
    ['unavailable', new HttpError(502, 'bad gateway'), 'Try again in a moment.'],
  ])('has no hint on the %s card, and keeps Try again where it had one', async (phase, err, hint) => {
    setSurface(true)
    infoMock.mockRejectedValue(err)
    const { container } = render(<BookingPage token="tok" />)
    await waitFor(() => expect(container.querySelector('.booking-lead')?.textContent).not.toMatch(/^Loading/i))
    expect(screen.queryByText(hint)).toBeNull()
    expect(container.querySelector('.hintline')).toBeNull()
    if (phase === 'unavailable') expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('keeps the hint on the same cards under a preset', async () => {
    infoMock.mockRejectedValue(new HttpError(404, 'unknown booking link'))
    render(<BookingPage token="tok" />)
    expect(await screen.findByText('Ask the person who sent it for a new link.')).toBeInTheDocument()
  })

  it('gives the busy chip no tooltip and the notes field no placeholder', async () => {
    setSurface(true)
    infoMock.mockResolvedValue(INFO)
    const { container } = render(<BookingPage token="tok" />)
    await screen.findByText('Intro call')
    // The chip is on the picking step, the notes field on the next.
    expect(container.querySelector('.busy-chip')).not.toBeNull()
    expect(container.querySelector('[title]')).toBeNull()
    fireEvent.click(container.querySelector('.slot-btn')!)
    expect(container.querySelector('[title]')).toBeNull()
    expect(container.querySelector('#booking-notes')!.hasAttribute('placeholder')).toBe(false)
  })

  it('keeps the tooltip and the placeholder under a preset', async () => {
    infoMock.mockResolvedValue(INFO)
    const { container } = render(<BookingPage token="tok" />)
    await screen.findByText('Intro call')
    expect(container.querySelector('.busy-chip')!.getAttribute('title')).toBe('The host is busy during this time')
    fireEvent.click(container.querySelector('.slot-btn')!)
    expect(container.querySelector('#booking-notes')!.getAttribute('placeholder')).toBe('Anything the host should know?')
  })
})

// ── the share page ────────────────────────────────────────────────────────

const T0 = new Date('2026-10-26T14:00:00.000Z')
const BASE: ShareView = {
  v: 1, generated_at: T0.toISOString(), poll_seconds: 30, day: '2026-10-26', days: 7,
  focus: null, lists: [], calendars: [], events: [], events_more: 0,
}
const WITH_ROWS: ShareView = {
  ...BASE, poll_seconds: 15,
  lists: [{ name: 'Work', color: '#3A7BD5', more: 0, tasks: [] }],
  focus: {
    state: 'focusing', phase: 'focus', phase_length_s: 1500,
    ends_at: new Date(T0.getTime() + 300_000).toISOString(), remaining_s: null,
    today: {
      rows: [
        { key: 'k1', title: 'Draft the memo', done: false, list: 0, due: null, all_day: false, private: false },
        { key: 'k3', title: 'Email Sam', done: true, list: 0, due: null, all_day: false, private: false },
      ],
      now: 'k1', next: [],
    },
  },
}
const fresh = (body: ShareView) => ({ status: 'fresh' as const, body, etag: 'e1' })

describe('<SharePage> under Field notes', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(T0) })
  afterEach(() => { vi.useRealTimers() })
  const settle = () => act(async () => { await vi.advanceTimersByTimeAsync(0) })

  it.each([
    ['gone', new HttpError(404, 'unknown share'), 'Reload later, or ask the person who shared it.'],
    ['unavailable', new HttpError(500, 'down'), 'Try again in a moment.'],
  ])('has no hint on the %s card', async (_p, err, hint) => {
    setSurface(true)
    viewMock.mockRejectedValue(err)
    const { container } = render(<SharePage token="tok" />)
    await settle()
    expect(container.querySelector('.share-gone__title')).not.toBeNull()
    expect(screen.queryByText(hint)).toBeNull()
    expect(container.querySelector('.hintline')).toBeNull()
    expect(container.querySelector('button.btn')).not.toBeNull()
  })

  it('keeps the hint on the gone card under a preset', async () => {
    viewMock.mockRejectedValue(new HttpError(404, 'unknown share'))
    render(<SharePage token="tok" />)
    await settle()
    expect(screen.getByText('Reload later, or ask the person who shared it.')).toBeInTheDocument()
  })

  it('draws a mark on every row and a strike on the name, and leaves the text as it was', async () => {
    setSurface(true)
    viewMock.mockResolvedValue(fresh(WITH_ROWS))
    const { container } = render(<SharePage token="tok" />)
    await settle()
    const rows = container.querySelectorAll('.share-row')
    expect(rows).toHaveLength(2)
    const done = container.querySelector('.share-row.is-done')!
    expect(done.querySelector('.share-row__mark .check-ink')).not.toBeNull()
    expect(done.querySelector('.share-row__name .strike-ink.on')).not.toBeNull()
    const open = container.querySelector('.share-row:not(.is-done)')!
    expect(open.querySelector('.share-row__name .strike-ink.on')).toBeNull()
    // The hidden "Done" stays outside the host the strike measures.
    expect(done.querySelector('.share-row__name .share-sr')).toBeNull()
    expect(done.querySelector('.share-row__text')!.textContent).toBe('Email Sam done')
    expect(open.querySelector('.share-row__text')!.textContent).toBe('Draft the memo')
  })

  it('draws nothing extra on the rows under a preset', async () => {
    viewMock.mockResolvedValue(fresh(WITH_ROWS))
    const { container } = render(<SharePage token="tok" />)
    await settle()
    expect(container.querySelector('.share-row__mark .check-ink')).toBeNull()
    expect(container.querySelector('.share-row__name')).toBeNull()
    expect(container.querySelector('.strike-ink')).toBeNull()
  })

  it('has no footer text, and no footer at all without a wake lock', async () => {
    setSurface(true)
    viewMock.mockResolvedValue(fresh(BASE))
    const { container, unmount } = render(<SharePage token="tok" />)
    await settle()
    expect(screen.queryByText('Read-only. Updates on its own.')).toBeNull()
    expect(container.querySelector('.share-foot')).toBeNull()
    unmount()

    Object.defineProperty(navigator, 'wakeLock', {
      configurable: true, value: { request: vi.fn().mockResolvedValue({ release: vi.fn(), released: false }) },
    })
    const again = render(<SharePage token="tok" />)
    await settle()
    expect(again.container.querySelector('.share-foot')).not.toBeNull()
    expect(screen.queryByText('Read-only. Updates on its own.')).toBeNull()
    expect(screen.getByRole('button', { name: 'Keep screen on' })).toBeInTheDocument()
  })

  it('keeps the footer text under a preset', async () => {
    viewMock.mockResolvedValue(fresh(BASE))
    render(<SharePage token="tok" />)
    await settle()
    expect(screen.getByText('Read-only. Updates on its own.')).toBeInTheDocument()
  })
})

// ── Display mode's bar ────────────────────────────────────────────────────

const FRAME: DisplayFrame = {
  display: { name: 'Smylte', mode: 'calendar', palette: 'color', refresh_seconds: 300, rotation: 0 },
  generated_at: '2026-11-06T12:00:00Z', day: '2026-11-06', language: 'en',
  time_format: '24h', sources: [],
  calendar: {
    month: '2026-11', title: 'November 2026',
    weekday_names: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
    too_small_text: '', too_small_hint: '', weeks: [],
  },
}

describe('<DisplayModeFrame> under Field notes', () => {
  const open = async () => {
    previewMock.mockResolvedValue(FRAME)
    const onMode = vi.fn()
    const view = render(
      <DisplayModeFrame mode="habits" onMode={onMode} onExit={() => {}} onExpire={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Display controls' }))
    return { ...view, onMode }
  }

  it('sets the three faces as a segmented control, with the same names and the open one pressed', async () => {
    setSurface(true)
    const { container, onMode } = await open()
    const tabs = container.querySelector('.dmode-bar .view-tabs')!
    const buttons = [...tabs.querySelectorAll('button.view-tab')]
    expect(buttons.map((b) => b.textContent)).toEqual(['The month', 'Habits + today', 'Now + next'])
    expect(buttons.map((b) => b.getAttribute('aria-pressed'))).toEqual(['false', 'true', 'false'])
    expect(buttons[1].classList.contains('active')).toBe(true)
    expect((tabs as HTMLElement).style.getPropertyValue('--n')).toBe('3')
    expect((tabs as HTMLElement).style.getPropertyValue('--i')).toBe('1')
    fireEvent.click(buttons[2])
    expect(onMode).toHaveBeenCalledWith('now')
  })

  it('keeps three ghost buttons in the bar under a preset', async () => {
    const { container } = await open()
    expect(container.querySelector('.dmode-bar .view-tabs')).toBeNull()
    expect(container.querySelectorAll('.dmode-bar__tab')).toHaveLength(3)
  })
})
