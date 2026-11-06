// The signed-in display mode: the desk unit's faces, fetched through the
// session with refs, and the writes a tap or a drag makes.
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BAR_IDLE_MS, DisplayModeFrame } from './DisplayModeFrame'
import { api, type DisplayFrame } from '../api'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  return {
    ...mod,
    api: {
      ...mod.api,
      displayPreview: vi.fn(), complete: vi.fn(), patchDayEntry: vi.fn(), patchEvent: vi.fn(),
    },
  }
})

const m = vi.mocked(api)

const base = {
  display: { name: 'Smylte', mode: 'calendar' as const, palette: 'color' as const,
    refresh_seconds: 300, rotation: 0 },
  generated_at: '2026-11-06T12:00:00Z', day: '2026-11-06', language: 'en',
  time_format: '24h' as const, sources: [],
}

const MONTH: DisplayFrame = {
  ...base,
  calendar: {
    month: '2026-11', title: 'November 2026',
    weekday_names: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
    too_small_text: '', too_small_hint: '',
    weeks: [[
      { day: '2026-11-06', label: '6', in_month: true, today: true, hidden: 0, items: [
        { text: 'Standup', time: '09:00', all_day: false, source: null, continued: false,
          ref: { calendar: 'cal-a', uid: 'e1', start: '2026-11-06T09:00:00',
            end: '2026-11-06T09:30:00', recurring: false } },
        { text: 'Weekly', time: '10:00', all_day: false, source: null, continued: false,
          ref: { calendar: 'cal-a', uid: 'e2', start: '2026-11-06T10:00:00',
            end: null, recurring: true } },
      ] },
      { day: '2026-11-07', label: '7', in_month: true, today: false, hidden: 0, items: [] },
      { day: '2026-11-09', label: '9', in_month: true, today: false, hidden: 0, items: [] },
    ]],
  },
}

const DAY: DisplayFrame = {
  ...base,
  display: { ...base.display, mode: 'habits' },
  habits: {
    planned: true, heading: 'Habits', day_heading: 'Today',
    habits: [{ text: 'Stretch', done: false, kind: 'habit', source: null, estimate_minutes: null,
      ref: { kind: 'habit', entry: 'en1', planned: true } }],
    tasks: [{ text: 'Invoice', done: false, kind: 'task', source: 'work', estimate_minutes: null,
      ref: { kind: 'task', entry: 'en2', planned: true, list: 'work', uid: 't1' } }],
    habits_hidden: 0, tasks_hidden: 0,
    counts: { habits_done: 0, habits_total: 1, tasks_done: 0, tasks_total: 1 },
    empty_text: '', all_done_text: '', preview_text: '', preview_hint: '',
  },
}

const NOW: DisplayFrame = {
  ...base,
  display: { ...base.display, mode: 'now' },
  now: {
    planned: true, heading: 'Now', next_heading: 'Next',
    current: { text: 'Invoice', kind: 'task', source: null, estimate: '', estimate_minutes: null,
      ref: { kind: 'task', entry: 'en2', planned: true, list: 'work', uid: 't1' } },
    next: null, remaining: 0, counts: { done: 0, total: 1 },
    empty_text: 'Nothing', all_done_text: 'All done', preview_text: '', preview_hint: '',
  },
}

beforeEach(() => {
  vi.clearAllMocks()
  m.complete.mockResolvedValue({} as never)
  m.patchDayEntry.mockResolvedValue({} as never)
  m.patchEvent.mockResolvedValue({} as never)
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  delete (navigator as unknown as Record<string, unknown>).wakeLock
  delete (document as unknown as Record<string, unknown>).elementFromPoint
})

const frame = (mode: 'calendar' | 'habits' | 'now' = 'calendar', over = {}) => (
  <DisplayModeFrame mode={mode} onMode={() => {}} onExit={() => {}} onExpire={() => {}} {...over} />
)

describe('<DisplayModeFrame>', () => {
  it('draws the desk unit\'s face for the mode, fetched with refs through the session', async () => {
    m.displayPreview.mockResolvedValue(MONTH)
    render(frame())
    expect(await screen.findByText('November 2026')).toBeInTheDocument()
    expect(m.displayPreview).toHaveBeenCalledWith('calendar', expect.any(String))
  })

  it('ticks a habit on its entry and a task on its VTODO, then fetches again', async () => {
    m.displayPreview.mockResolvedValue(DAY)
    render(frame('habits'))
    fireEvent.click(await screen.findByRole('button', { name: 'Stretch' }))
    await waitFor(() => expect(m.patchDayEntry).toHaveBeenCalledWith('2026-11-06', 'en1', { done: true }))
    fireEvent.click(screen.getByRole('button', { name: 'Invoice' }))
    await waitFor(() => expect(m.complete).toHaveBeenCalledWith('work', 't1', true))
    await waitFor(() => expect(m.displayPreview.mock.calls.length).toBeGreaterThanOrEqual(3))
  })

  it('leaves a habit on an unplanned day alone: its entry does not exist yet', async () => {
    const preview = structuredClone(DAY)
    preview.habits!.planned = false
    preview.habits!.habits[0].ref = { kind: 'habit', entry: 'en1', planned: false }
    m.displayPreview.mockResolvedValue(preview)
    render(frame('habits'))
    expect(await screen.findByText('Stretch')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Stretch' })).toBeNull()
    // A task is done on its VTODO, which exists whether or not the day does.
    expect(screen.getByRole('button', { name: 'Invoice' })).toBeInTheDocument()
  })

  it('finishes the current item with a tap on the now face', async () => {
    m.displayPreview.mockResolvedValue(NOW)
    render(frame('now'))
    fireEvent.click(await screen.findByRole('button', { name: 'Invoice' }))
    await waitFor(() => expect(m.complete).toHaveBeenCalledWith('work', 't1', true))
  })

  it('moves an event by the days between the cells it is dragged across', async () => {
    m.displayPreview.mockResolvedValue(MONTH)
    render(frame())
    const chip = (await screen.findByText('Standup')).closest('.display-chip') as HTMLElement
    const target = document.querySelector('[data-day="2026-11-09"]') as HTMLElement
    document.elementFromPoint = vi.fn(() => target)
    fireEvent.pointerDown(chip, { button: 0, pointerId: 1, clientX: 10, clientY: 10 })
    fireEvent.pointerMove(chip, { pointerId: 1, clientX: 200, clientY: 10 })
    await waitFor(() => expect(target).toHaveClass('is-over'))
    fireEvent.pointerUp(chip, { pointerId: 1, clientX: 200, clientY: 10 })
    await waitFor(() => expect(m.patchEvent).toHaveBeenCalledWith('cal-a', 'e1', {
      start: '2026-11-09T09:00', end: '2026-11-09T09:30',
    }))
  })

  it('treats a press that barely moves as a tap, and does not move a repeating event', async () => {
    m.displayPreview.mockResolvedValue(MONTH)
    render(frame())
    const chip = (await screen.findByText('Standup')).closest('.display-chip') as HTMLElement
    document.elementFromPoint = vi.fn(() => document.querySelector('[data-day="2026-11-09"]'))
    fireEvent.pointerDown(chip, { button: 0, pointerId: 1, clientX: 10, clientY: 10 })
    fireEvent.pointerMove(chip, { pointerId: 1, clientX: 13, clientY: 12 })
    fireEvent.pointerUp(chip, { pointerId: 1 })
    const weekly = screen.getByText('Weekly').closest('.display-chip') as HTMLElement
    expect(weekly).not.toHaveClass('is-draggable')
    expect(chip).toHaveClass('is-draggable')
    expect(m.patchEvent).not.toHaveBeenCalled()
  })

  it('keeps the screen awake while it is up, and lets go when it is not', async () => {
    m.displayPreview.mockResolvedValue(MONTH)
    const release = vi.fn(async () => {})
    const request = vi.fn(async () => ({ released: false, release }))
    Object.defineProperty(navigator, 'wakeLock', { configurable: true, value: { request } })
    const { unmount } = render(frame())
    await act(async () => {})
    expect(request).toHaveBeenCalledWith('screen')
    unmount()
    expect(release).toHaveBeenCalled()
  })

  it('switches faces and exits from its bar, which folds away when left alone', async () => {
    m.displayPreview.mockResolvedValue(MONTH)
    const onMode = vi.fn()
    const onExit = vi.fn()
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(frame('calendar', { onMode, onExit }))
    fireEvent.click(screen.getByRole('button', { name: 'Display controls' }))
    fireEvent.click(screen.getByRole('button', { name: 'Habits + today' }))
    expect(onMode).toHaveBeenCalledWith('habits')
    fireEvent.click(screen.getByRole('button', { name: 'Exit display mode' }))
    expect(onExit).toHaveBeenCalled()
    act(() => { vi.advanceTimersByTime(BAR_IDLE_MS) })
    expect(screen.queryByRole('toolbar')).toBeNull()
  })
})
