import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FocusView } from './FocusView'
import { DataProvider } from '../data'
import { api, type DayEntry, type DayPlan, type FocusSession } from '../api'
import { DEFAULT_FOCUS } from '../focus'
import { playChime } from '../chime'
import { showNotify } from '../notify'

// The whole API module, like every other component suite here: each method
// becomes a vi.fn(), so nothing touches the network and the session endpoints
// can be driven directly.
vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
// The two device-facing modules, so a test can see that the surface ASKED for
// a sound without jsdom needing an audio graph.
vi.mock('../chime', () => ({
  playChime: vi.fn(), unlockChime: vi.fn(), chimeReady: vi.fn(() => true), _resetChime: vi.fn(),
}))
vi.mock('../notify', () => ({
  showNotify: vi.fn(() => true), notifyPermission: vi.fn(() => 'granted'),
  requestNotify: vi.fn(async () => 'granted'),
}))

const m = vi.mocked(api)

const pad = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const today = () => ymd(new Date())

const entry = (o: Partial<DayEntry> = {}): DayEntry => ({
  entry_id: 'n1', day: today(), kind: 'note', list: null, uid: null,
  title: 'Memo', source: 'user', position: 1,
  done_at: null, dropped_at: null, habit_id: null, rolled_to: null,
  estimate_minutes: null, worked_seconds: null, capped: null,
  created_at: '2026-09-03T08:00:00.000Z', ...o,
})
const plan = (entries: DayEntry[], o: Partial<DayPlan> = {}): DayPlan => ({
  day: today(), planned: true, entries, capacity_minutes: null, capacity: null,
  committed_at: null, shutdown_at: null, reflection: null, ...o,
})
/** A session anchored `agoS` seconds before the (fake) clock's now. */
const session = (o: Partial<FocusSession> = {}, agoS = 0): FocusSession => ({
  day: today(), phase: 'focus', phase_length_s: 1500, phase_elapsed_s: 0,
  running_since: new Date(Date.now() - agoS * 1000).toISOString(),
  intervals_done: 0, entry_id: 'n1', passed: [],
  started_at: new Date().toISOString(), ended_at: null, updated_at: new Date().toISOString(),
  ...o,
})
const FOUR = [
  entry({ entry_id: 'n1', title: 'Memo', position: 1 }),
  entry({ entry_id: 'n2', title: 'Invoice', position: 2 }),
  entry({ entry_id: 'n3', title: 'Call', position: 3 }),
  entry({ entry_id: 'n4', title: 'Filing', position: 4 }),
]

function show(settings = DEFAULT_FOCUS) {
  const onLeave = vi.fn()
  render(
    <DataProvider rev={0} onExpire={vi.fn()}>
      <FocusView rev={0} focusRev={0} onExpire={vi.fn()} onLeave={onLeave} settings={settings} />
    </DataProvider>,
  )
  return { onLeave, user: userEvent.setup({ advanceTimers: vi.advanceTimersByTime }) }
}

const tick = (seconds: number) => act(() => { vi.advanceTimersByTime(seconds * 1000) })

beforeEach(() => {
  vi.clearAllMocks()
  // Real time still moves under the fake clock, so `findBy*` polls; the
  // surface's own second-hand is driven by `tick`.
  vi.useFakeTimers({ shouldAdvanceTime: true })
  localStorage.clear()
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.day.mockResolvedValue(plan(FOUR))
  m.focus.mockResolvedValue(session())
  m.focusClock.mockImplementation(async (_d, body) => session({ phase: body.action === 'next' ? 'break' : 'focus' }))
  m.focusCursor.mockResolvedValue(session({ entry_id: 'n2', passed: ['n1'] }))
  m.startFocus.mockResolvedValue(session())
  m.patchDayEntry.mockImplementation(async (_d, id, body) => entry({ entry_id: id, ...body }))
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  document.title = 'Smylte'
})

describe('<FocusView>', () => {
  it('paints the row the server named, the one after it, and the count behind that', async () => {
    show()
    expect(await screen.findByRole('heading', { name: 'Memo' })).toBeInTheDocument()
    expect(screen.getByText('Invoice')).toBeInTheDocument()
    expect(screen.getByText('+2 behind that')).toBeInTheDocument()
    expect(screen.getByText('25:00')).toBeInTheDocument()
    expect(screen.getByText('1 / 4 done'.replace('1', '0'))).toBeInTheDocument()
    // The clock is derived from the anchor, so a minute later reads a minute less.
    tick(61)
    expect(screen.getByText('23:59')).toBeInTheDocument()
    expect(document.title).toBe('23:59 · Memo · Smylte')
  })

  it('sets a capped row aside the moment its estimate is used up, once', async () => {
    m.day.mockResolvedValue(plan([
      entry({ entry_id: 'n1', title: 'Memo', estimate_minutes: 1, capped: true, worked_seconds: 55 }),
      entry({ entry_id: 'n2', title: 'Invoice', position: 2 }),
    ]))
    show()
    await screen.findByRole('heading', { name: 'Memo' })
    expect(m.focusCursor).not.toHaveBeenCalled()
    tick(6)
    expect(m.focusCursor).toHaveBeenCalledWith(today(), { action: 'pass', entry_id: 'n1' })
    // The next row is painted at once, and the ask is not repeated on later ticks.
    expect(await screen.findByRole('heading', { name: 'Invoice' })).toBeInTheDocument()
    tick(30)
    expect(m.focusCursor).toHaveBeenCalledTimes(1)
  })

  it('never passes a row that runs until done', async () => {
    m.day.mockResolvedValue(plan([
      entry({ entry_id: 'n1', title: 'Memo', estimate_minutes: 1, capped: false, worked_seconds: 3000 }),
    ]))
    show()
    await screen.findByRole('heading', { name: 'Memo' })
    tick(120)
    expect(m.focusCursor).not.toHaveBeenCalled()
  })

  it('says so, sounds, and rolls on at the end of an interval — on a live screen', async () => {
    // Anchored 25 minutes ago: over the moment it paints, and not away.
    m.focus.mockResolvedValue(session({}, 1500))
    show({ ...DEFAULT_FOCUS, autoContinue: true, notify: true })
    await screen.findByRole('heading', { name: 'Memo' })
    tick(1)
    expect(playChime).toHaveBeenCalledWith('focus')
    expect(showNotify).toHaveBeenCalledWith('Interval over', 'Memo')
    expect(m.focusClock).toHaveBeenCalledWith(today(), {
      action: 'next', expect_phase: 'focus', expect_intervals: 0, skip_break: false,
    })
    // Once. The break the server answered with is a new phase, and its end is
    // its own event.
    tick(5)
    expect(playChime).toHaveBeenCalledTimes(1)
    expect(m.focusClock).toHaveBeenCalledTimes(1)
  })

  it('waits, silently, when the interval ended while nobody was here', async () => {
    // Anchored 25 minutes plus three ago: over, and past the grace.
    m.focus.mockResolvedValue(session({}, 1500 + 180))
    show({ ...DEFAULT_FOCUS, autoContinue: true })
    await screen.findByRole('heading', { name: 'Memo' })
    tick(2)
    expect(screen.getByText('Interval over · you were away')).toBeInTheDocument()
    expect(screen.getByText('0:00')).toBeInTheDocument()
    expect(playChime).not.toHaveBeenCalled()
    expect(showNotify).not.toHaveBeenCalled()
    expect(m.focusClock).not.toHaveBeenCalled()
    // The owner is back: the way on is theirs.
    expect(screen.getByRole('button', { name: 'Take a break' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Keep going' })).toBeInTheDocument()
  })

  it('stops and waits at the end of an interval when told to', async () => {
    m.focus.mockResolvedValue(session({}, 1500))
    const { user } = show()
    await screen.findByRole('heading', { name: 'Memo' })
    tick(1)
    expect(playChime).toHaveBeenCalledWith('focus')
    expect(m.focusClock).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Keep going' }))
    expect(m.focusClock).toHaveBeenCalledWith(today(), {
      action: 'next', expect_phase: 'focus', expect_intervals: 0, skip_break: true,
    })
  })

  it('ticks a note through the day, and lets the server move the cursor', async () => {
    const { user } = show()
    await screen.findByRole('heading', { name: 'Memo' })
    await user.click(screen.getByRole('button', { name: 'Done' }))
    expect(m.patchDayEntry).toHaveBeenCalledWith(today(), 'n1', { done: true })
    // The row is finished on this screen; the ONE fact that earns a sync.
    await vi.waitFor(() => {
      expect(m.focusClock).toHaveBeenCalledWith(today(), { action: 'sync' })
    })
    expect(m.focusClock).toHaveBeenCalledTimes(1)
  })

  it('pauses and resumes from the anchor', async () => {
    m.focusClock.mockImplementation(async (_d, body) =>
      body.action === 'pause' ? session({ running_since: null, phase_elapsed_s: 60 }) : session({ phase_elapsed_s: 60 }))
    const { user } = show()
    await screen.findByRole('heading', { name: 'Memo' })
    tick(60)
    await user.click(screen.getByRole('button', { name: 'Pause' }))
    expect(m.focusClock).toHaveBeenCalledWith(today(), { action: 'pause' })
    expect(await screen.findByText('Paused')).toBeInTheDocument()
    tick(600)
    expect(screen.getByText('24:00')).toBeInTheDocument()   // a paused clock does not move
    await user.click(screen.getByRole('button', { name: 'Resume' }))
    expect(m.focusClock).toHaveBeenCalledWith(today(), { action: 'resume' })
  })

  it('offers Start when there is no session, and points at Today when there is no plan', async () => {
    m.focus.mockResolvedValue(null)
    const { user } = show()
    await user.click(await screen.findByRole('button', { name: 'Start working' }))
    expect(m.startFocus).toHaveBeenCalledWith(today())
    cleanup()
    m.day.mockResolvedValue(plan([], { planned: false }))
    const { onLeave, user: user2 } = show()
    expect(await screen.findByText("Today isn't planned yet.")).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start working' })).not.toBeInTheDocument()
    await user2.click(screen.getByRole('button', { name: 'Back to today' }))
    expect(onLeave).toHaveBeenCalled()
    // Never `openDay`: Today is the only opener.
    expect(m.openDay).not.toHaveBeenCalled()
  })

  it('leaves on an Escape dispatched at the window', async () => {
    const { onLeave } = show()
    await screen.findByRole('heading', { name: 'Memo' })
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onLeave).toHaveBeenCalledTimes(1)
  })

  it('says when the queue is dry, and offers another round over what was set aside', async () => {
    m.focus.mockResolvedValue(session({ entry_id: null, passed: ['n1', 'n2', 'n3', 'n4'] }))
    m.focusCursor.mockResolvedValue(session())
    const { user } = show()
    expect(await screen.findByText('Nothing left in the queue.')).toBeInTheDocument()
    expect(screen.getByText('4 set aside')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Go round again' }))
    expect(m.focusCursor).toHaveBeenCalledWith(today(), { action: 'again' })
    expect(await screen.findByRole('heading', { name: 'Memo' })).toBeInTheDocument()
  })
})
