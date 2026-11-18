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
// The Windows client's bridge. Null everywhere by default — a browser — so
// the suite above never sees a float control; the floating cases below hand
// it a host to talk to.
vi.mock('../desktop', () => ({
  readState: vi.fn(async () => null),
  floatWindow: vi.fn(async () => null),
  dockWindow: vi.fn(async () => null),
  pinWindow: vi.fn(async () => null),
  dragWindow: vi.fn(async () => null),
  isFloatWindow: vi.fn(() => false),
}))
import { dockWindow, dragWindow, floatWindow, pinWindow, readState } from '../desktop'

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
  committed_at: null, committed_over_minutes: null, shutdown_at: null, reflection: null, ...o,
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

function show(settings = DEFAULT_FOCUS, floating = false) {
  const onLeave = vi.fn()
  render(
    <DataProvider rev={0} onExpire={vi.fn()}>
      <FocusView rev={0} focusRev={0} onExpire={vi.fn()} onLeave={onLeave} settings={settings}
        floating={floating} />
    </DataProvider>,
  )
  return { onLeave, user: userEvent.setup({ advanceTimers: vi.advanceTimersByTime }) }
}

const tick = (seconds: number) => act(() => { vi.advanceTimersByTime(seconds * 1000) })

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers({ shouldAdvanceTime: true })
  localStorage.clear()
  // Before the render: `useFieldNotes` reads the attribute when it mounts.
  document.documentElement.setAttribute('data-surface', 'app')
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.day.mockResolvedValue(plan(FOUR))
  m.focus.mockResolvedValue(session())
  vi.mocked(readState).mockResolvedValue(null)
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  document.documentElement.removeAttribute('data-surface')
  document.title = 'Smylte'
})

describe('<FocusView> under Field notes', () => {
  it('names an unplanned day and does not say what to do about it', async () => {
    m.day.mockResolvedValue(plan([], { planned: false }))
    show()
    expect(await screen.findByText("Today isn't planned yet.")).toBeInTheDocument()
    expect(screen.queryByText('Open Today first.')).not.toBeInTheDocument()
  })

  it('has no away hint when the interval ended while nobody was here', async () => {
    m.focus.mockResolvedValue(session({}, 1500 + 180))
    show()
    await screen.findByRole('heading', { name: 'Memo' })
    tick(2)
    expect(screen.getByText('Interval over · you were away')).toBeInTheDocument()
    expect(screen.queryByText('The clock stopped when the interval ended.')).not.toBeInTheDocument()
  })

  it('carries no tooltip in the main window', async () => {
    show()
    await screen.findByRole('heading', { name: 'Memo' })
    expect(screen.getByRole('button', { name: 'Invoice' })).toBeInTheDocument()
    expect(document.body.querySelector('[title]')).toBeNull()
  })

  it('carries no tooltip when floating, and the pin keeps its name', async () => {
    vi.mocked(readState).mockResolvedValue({
      available: true, choice: 'Auto', resolved: 'Ink', systemUsesLightTheme: true,
      startMenuShortcut: false, captionColour: true, floating: true, pinned: true, nativeDrag: true,
    })
    show(DEFAULT_FOCUS, true)
    await screen.findByRole('heading', { name: 'Memo' })
    expect(await screen.findByRole('button', { name: 'Let it fall behind' })).toBeInTheDocument()
    expect(document.body.querySelector('[title]')).toBeNull()
  })
})
