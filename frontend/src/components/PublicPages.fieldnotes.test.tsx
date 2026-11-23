// The booking page, the share page and Display mode's bar under Field notes
// (`data-surface="app"`): the hints and tooltips are not rendered, the share
// rows carry the drawn mark and strike, and the bar's three faces are a
// segmented control. Every one of these is the preset's markup when the
// attribute is absent, so each test also looks at that side.
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BookingPage } from './BookingPage'
import { SharePage, ShareBody } from './SharePage'
import { DisplayModeFrame } from './DisplayModeFrame'
import { api, HttpError, type DisplayFrame, type PublicBookingInfo, type ShareView } from '../api'
import { translate } from '../i18n/index'
import FIXTURE from '../test/drawing-fixture.json'
import { evaluate, type Atom } from '../drawing'
import { shareDayState } from '../share'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  return {
    ...mod,
    api: {
      ...mod.api,
      publicBookingInfo: vi.fn(), publicBook: vi.fn(), publicShareView: vi.fn(), displayPreview: vi.fn(),
      publicShareDrawing: vi.fn(),
    },
  }
})

const infoMock = vi.mocked(api.publicBookingInfo)
const viewMock = vi.mocked(api.publicShareView)
const previewMock = vi.mocked(api.displayPreview)
const drawMock = vi.mocked(api.publicShareDrawing)

const setSurface = (on: boolean) => {
  if (on) document.documentElement.setAttribute('data-surface', 'app')
  else document.documentElement.removeAttribute('data-surface')
}

beforeEach(() => {
  infoMock.mockReset()
  viewMock.mockReset()
  previewMock.mockReset()
  drawMock.mockReset()
  drawMock.mockResolvedValue(null)
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
const RICH: ShareView = {
  ...WITH_ROWS,
  calendars: [{ name: 'Home', color: '#5B8C5A' }],
  events: [{ title: 'Standup', start: new Date(T0.getTime() + 3_600_000).toISOString(),
    end: new Date(T0.getTime() + 5_400_000).toISOString(), all_day: false, calendar: 0, private: false }],
  lists: [
    { name: 'Work', color: '#3A7BD5', more: 0,
      tasks: [{ title: 'Quarterly report', due: null, all_day: false, depth: 0, private: false }] },
    { name: 'Home', color: null, more: 0, tasks: [] },
  ],
}
const IDLE: ShareView = {
  ...WITH_ROWS, poll_seconds: 30,
  focus: {
    state: 'idle', phase: null, phase_length_s: null, ends_at: null, remaining_s: null,
    today: {
      rows: [
        { key: 'k1', title: 'Draft the memo', done: false, list: 0, due: null, all_day: false, private: false },
        { key: 'k2', title: 'Call printer', done: false, list: 0, due: null, all_day: false, private: false },
      ],
      now: null, next: ['k1', 'k2'],
    },
  },
}
const fresh = (body: ShareView) => ({ status: 'fresh' as const, body, etag: 'e1' })
const TWO_DONE: ShareView = {
  ...WITH_ROWS,
  focus: {
    ...WITH_ROWS.focus!,
    today: { ...WITH_ROWS.focus!.today, rows: WITH_ROWS.focus!.today.rows.map((r) => ({ ...r, done: true })) },
  },
}
const DRAWN = { ...FIXTURE, view: 'today', day: '2026-10-26', theme: 'light' }
const rewardsOn = (c: HTMLElement) => c.querySelectorAll('.share-drawing .dm-reward.on').length
const expectedRewards = (v: ShareView) => FIXTURE.marks.filter((m) => m.reward !== null
  && evaluate(m.when as Atom[], shareDayState(v, Date.now(), 0))).length

describe('<SharePage> under Field notes', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(T0) })
  afterEach(() => { vi.useRealTimers() })
  const settle = (ms = 0) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })

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

  it('sets the date as Today does, with a dot between Live and Read-only', async () => {
    setSurface(true)
    viewMock.mockResolvedValue(fresh(WITH_ROWS))
    const { container } = render(<SharePage token="tok" />)
    await settle()
    expect(container.querySelector('.share-head__weekday')!.textContent).toBe('Monday')
    expect(container.querySelector('.share-head__date')!.textContent).toBe('Oct 26')
    expect(container.querySelector('.share-head__day')!.textContent).toBe('Monday Oct 26')
    const meta = container.querySelector('.share-head__meta')!
    expect([...meta.children].map((c) => c.className)).toEqual(['share-live', 'share-sep', 'share-readonly'])
    const sep = container.querySelector('.share-sep')!
    expect(sep.getAttribute('aria-hidden')).toBe('true')
    expect(sep.textContent).toBe('·')
  })

  it('lays Today out after the focus card, and the agenda and the lists on the paper', async () => {
    setSurface(true)
    viewMock.mockResolvedValue(fresh(RICH))
    const { container } = render(<SharePage token="tok" />)
    await settle()
    expect(container.querySelector('.share-presence .share-today')).toBeNull()
    const today = container.querySelector('section.share-today.share-section')!
    expect(today).not.toBeNull()
    const card = container.querySelector('.share-presence')!
    expect(card.compareDocumentPosition(today) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(today.querySelectorAll('.share-row')).toHaveLength(2)
    const agenda = container.querySelector('.share-agenda')!
    expect(agenda.classList.contains('share-section')).toBe(true)
    expect(agenda.classList.contains('share-card')).toBe(false)
    const lists = container.querySelectorAll('details.share-list.share-section')
    expect(lists).toHaveLength(2)
    for (const l of lists) {
      expect(l.classList.contains('share-card')).toBe(false)
      const chev = l.querySelector('summary')!.lastElementChild!
      expect(chev.matches('svg.share-list__chev')).toBe(true)
      expect(chev.getAttribute('aria-hidden')).toBe('true')
    }
  })

  it('puts the highlighter behind the title being worked on, and draws the interval', async () => {
    setSurface(true)
    viewMock.mockResolvedValue(fresh(WITH_ROWS))
    const { container } = render(<SharePage token="tok" />)
    await settle()
    expect(container.querySelector('.share-now__title > .share-now__ink')!.textContent).toBe('Draft the memo')
    expect(container.querySelector('.share-presence__bar')).toBeNull()
    expect(container.querySelector('svg.share-line[aria-hidden="true"]')).not.toBeNull()
    // ends_at is 300 s away in a 1500 s phase: 0.8 of it has gone.
    const ink = container.querySelector('.share-line__ink')!
    expect(Number(ink.getAttribute('stroke-dashoffset'))).toBeCloseTo(0.2, 3)
  })

  it('separates the tasks up next with a dot', async () => {
    setSurface(true)
    viewMock.mockResolvedValue(fresh(IDLE))
    const { container } = render(<SharePage token="tok" />)
    await settle()
    expect(container.querySelector('.share-then')!.textContent).toBe('Up next Draft the memo · Call printer')
  })

  it('gives the Settings preview the same single column', () => {
    setSurface(true)
    const { container } = render(
      <ShareBody view={RICH} nowMs={T0.getTime()} skewMs={0} tr={(k, v) => translate('en', k, v)}
        locale="en-US" justDone={new Set()} />)
    const card = container.querySelector('.share-presence')!
    const today = container.querySelector('section.share-today.share-section')!
    expect(today).not.toBeNull()
    expect(card.compareDocumentPosition(today) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(container.querySelector('.share-agenda.share-section')).not.toBeNull()
  })

  it('keeps the preset page as it was', async () => {
    viewMock.mockResolvedValue(fresh(RICH))
    const first = render(<SharePage token="tok" />)
    await settle()
    const c = first.container
    expect(c.querySelector('.share-presence .share-today')).not.toBeNull()
    expect(c.querySelectorAll('.share-section')).toHaveLength(0)
    expect(c.querySelector('.share-agenda.share-card')).not.toBeNull()
    expect(c.querySelectorAll('details.share-list.share-card')).toHaveLength(2)
    for (const sel of ['.share-list__chev', '.share-sep', '.share-now__ink', '.share-line', '.share-head__weekday']) {
      expect(c.querySelector(sel), sel).toBeNull()
    }
    expect(c.querySelector('.share-presence__bar')).not.toBeNull()
    expect(c.querySelector('.share-head__day')!.textContent).toBe('Monday, October 26')
    first.unmount()

    viewMock.mockResolvedValue(fresh(IDLE))
    const second = render(<SharePage token="tok" />)
    await settle()
    expect(second.container.querySelector('.share-then')!.textContent).toBe('Up next Draft the memo Call printer')
  })

  it('draws the owner’s drawing beside the date, fetched once', async () => {
    setSurface(true)
    viewMock.mockResolvedValue(fresh(WITH_ROWS))
    drawMock.mockResolvedValue(DRAWN)
    const { container } = render(<SharePage token="tok" />)
    await settle()
    await settle()
    expect(drawMock).toHaveBeenCalledTimes(1)
    expect(drawMock).toHaveBeenCalledWith('tok', 'light', expect.any(AbortSignal))
    const svg = container.querySelector('.share-head.share-head--drawn > svg.day-drawing.share-drawing')
    expect(svg).not.toBeNull()
    expect(svg!.getAttribute('data-subject')).toBe('desk')
    // A second poll on the same day asks for no second drawing.
    await settle(15_000)
    expect(viewMock).toHaveBeenCalledTimes(2)
    expect(drawMock).toHaveBeenCalledTimes(1)
  })

  it('grows a reward as a shared row is ticked', async () => {
    setSurface(true)
    viewMock.mockResolvedValueOnce(fresh(WITH_ROWS)).mockResolvedValue(fresh(TWO_DONE))
    drawMock.mockResolvedValue(DRAWN)
    const { container } = render(<SharePage token="tok" />)
    await settle()
    await settle()
    const first = rewardsOn(container)
    expect(first).toBe(expectedRewards(WITH_ROWS))
    await settle(15_000)
    expect(rewardsOn(container)).toBe(expectedRewards(TWO_DONE))
    expect(rewardsOn(container)).toBeGreaterThan(first)
  })

  it('asks again when the day turns, and shows no drawing for another day', async () => {
    setSurface(true)
    viewMock.mockResolvedValueOnce(fresh(WITH_ROWS)).mockResolvedValue(fresh({ ...WITH_ROWS, day: '2026-10-27' }))
    drawMock.mockResolvedValue(DRAWN)
    const { container } = render(<SharePage token="tok" />)
    await settle()
    await settle()
    expect(container.querySelector('.share-drawing')).not.toBeNull()
    await settle(15_000)
    await settle()
    expect(drawMock).toHaveBeenCalledTimes(2)
    expect(container.querySelector('.share-drawing')).toBeNull()
  })

  it('asks in the viewer’s theme', async () => {
    setSurface(true)
    localStorage.setItem('smylte-theme', 'dark')
    document.documentElement.dataset.theme = 'dark'
    try {
      viewMock.mockResolvedValue(fresh(WITH_ROWS))
      render(<SharePage token="tok" />)
      await settle()
      await settle()
      expect(drawMock).toHaveBeenCalledWith('tok', 'dark', expect.any(AbortSignal))
    } finally {
      localStorage.removeItem('smylte-theme')
      delete document.documentElement.dataset.theme
    }
  })

  it('never takes a drawing 404 for the link going', async () => {
    setSurface(true)
    viewMock.mockResolvedValue(fresh(WITH_ROWS))
    drawMock.mockRejectedValue(new HttpError(404, 'unknown share'))
    const { container } = render(<SharePage token="tok" />)
    await settle()
    await settle()
    expect(drawMock).toHaveBeenCalledTimes(1)
    expect(container.querySelector('.share-presence')).not.toBeNull()
    expect(container.querySelector('.share-gone__title')).toBeNull()
    expect(container.querySelector('.share-drawing')).toBeNull()
    expect(viewMock).toHaveBeenCalledTimes(1)
  })

  it('drops the drawing when the link goes', async () => {
    setSurface(true)
    viewMock.mockResolvedValueOnce(fresh(WITH_ROWS)).mockRejectedValue(new HttpError(404, 'unknown share'))
    drawMock.mockResolvedValue(DRAWN)
    const { container } = render(<SharePage token="tok" />)
    await settle()
    await settle()
    expect(container.querySelector('.share-drawing')).not.toBeNull()
    await settle(15_000)
    await settle()
    expect(container.querySelector('.share-gone__title')).not.toBeNull()
    expect(container.querySelector('.share-drawing')).toBeNull()
    expect(drawMock).toHaveBeenCalledTimes(1)
    // The gone card shows no drawing whatever the state holds, so the link
    // comes back with a drawing still on its way: only one dropped when the
    // link went leaves the page without one.
    viewMock.mockResolvedValue(fresh(WITH_ROWS))
    drawMock.mockReturnValue(new Promise(() => {}))
    fireEvent.click(screen.getByRole('button', { name: 'Check again' }))
    await settle()
    await settle()
    expect(container.querySelector('.share-presence')).not.toBeNull()
    expect(container.querySelector('.share-drawing')).toBeNull()
    expect(drawMock).toHaveBeenCalledTimes(2)
  })

  it('draws nothing that fails validation', async () => {
    setSurface(true)
    viewMock.mockResolvedValue(fresh(WITH_ROWS))
    drawMock.mockResolvedValue({ ...DRAWN, marks: [{ id: 'a', role: 'line', frames: ['<script>'], when: [], reward: null }] })
    const { container } = render(<SharePage token="tok" />)
    await settle()
    await settle()
    expect(drawMock).toHaveBeenCalledTimes(1)
    expect(container.querySelector('.share-drawing')).toBeNull()
  })

  it('asks for no drawing without the focus card or a list, or under a preset', async () => {
    const renders: [boolean, ShareView][] = [
      [true, { ...BASE, calendars: [{ name: 'Home', color: null }] }],
      [true, { ...WITH_ROWS, lists: [] }],
      [false, WITH_ROWS],
    ]
    for (const [on, view] of renders) {
      setSurface(on)
      viewMock.mockResolvedValue(fresh(view))
      const { container, unmount } = render(<SharePage token="tok" />)
      await settle()
      await settle()
      expect(container.querySelector('.share-presence, .share-agenda'), 'the page did not render').not.toBeNull()
      if (!on) expect(container.querySelector('.share-side')).toBeNull()
      unmount()
    }
    expect(drawMock).not.toHaveBeenCalled()
  })

  it('lays the page out in the board’s two columns', async () => {
    setSurface(true)
    Object.defineProperty(navigator, 'wakeLock', {
      configurable: true, value: { request: vi.fn().mockResolvedValue({ release: vi.fn(), released: false }) },
    })
    viewMock.mockResolvedValue(fresh(RICH))
    const { container } = render(<SharePage token="tok" />)
    await settle()
    await settle()
    expect(container.querySelector('.share-wrap.share-wrap--board > main.share.share--board')).not.toBeNull()
    const side = container.querySelector('.share-side')!
    expect([...side.children].map((c) => c.tagName.toLowerCase())).toEqual(['header', 'section'])
    expect(side.children[0].classList.contains('share-head')).toBe(true)
    expect(side.children[1].classList.contains('share-presence')).toBe(true)
    const main = container.querySelector('.share-main')!
    expect([...main.children].map((c) => c.className)).toEqual([
      'share-today share-section', 'share-agenda share-section',
      'share-list share-section', 'share-list share-section', 'share-foot',
    ])
  })

  it('holds the left column in view only where it fits the window, measured', async () => {
    setSurface(true)
    const offset = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight')!
    const inner = Object.getOwnPropertyDescriptor(window, 'innerHeight')!
    let sideHeight = 778
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
      configurable: true, get(this: HTMLElement) { return this.classList.contains('share-side') ? sideHeight : 0 },
    })
    const windowAt = (h: number) => Object.defineProperty(window, 'innerHeight', { configurable: true, value: h })
    const resize = () => act(() => { window.dispatchEvent(new Event('resize')) })
    try {
      windowAt(900)
      viewMock.mockResolvedValue(fresh(RICH))
      const { container } = render(<SharePage token="tok" />)
      await settle()
      await settle()
      const wrap = () => container.querySelector('.share-wrap')!
      expect(wrap()).toHaveClass('share-wrap--board')
      expect(wrap(), '778 under a 900 window').toHaveClass('share-wrap--sticky')
      windowAt(760)
      resize()
      expect(wrap(), '778 under a 760 window').not.toHaveClass('share-wrap--sticky')
      sideHeight = 900
      windowAt(900)
      resize()
      expect(wrap(), '900 under a 900 window').not.toHaveClass('share-wrap--sticky')
    } finally {
      Object.defineProperty(HTMLElement.prototype, 'offsetHeight', offset)
      Object.defineProperty(window, 'innerHeight', inner)
    }
  })

  it('keeps the Settings preview free of the board and the drawing', () => {
    setSurface(true)
    const { container } = render(
      <ShareBody view={RICH} nowMs={T0.getTime()} skewMs={0} tr={(k, v) => translate('en', k, v)}
        locale="en-US" justDone={new Set()} />)
    expect(container.querySelector('.share-presence')).not.toBeNull()
    expect(container.querySelector('.share-side')).toBeNull()
    expect(container.querySelector('.share-drawing')).toBeNull()
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
