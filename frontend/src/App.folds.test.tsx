// When App lets the fold follower run. It may re-key a fold only against the
// account's own folds for THIS session: before the session's settings read
// lands, `collapsedTasks` is the empty default or what the previous session
// left, and a re-key of either would be written over the account.
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api } from './api'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)

vi.mock('./desktop', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./desktop')>()
  return {
    ...mod,
    readState: vi.fn(async () => null),
    floatWindow: vi.fn(async () => null), dockWindow: vi.fn(async () => null),
    pinWindow: vi.fn(async () => null), dragWindow: vi.fn(async () => null),
  }
})

// The follower itself is tested in FoldFollower.test.tsx. Here it only says
// whether it is mounted and which folds it was handed.
vi.mock('./components/FoldFollower', () => ({
  FoldFollower: ({ collapsed }: { collapsed: string[] }) =>
    <div data-testid="fold-follower">{collapsed.join(' ') || '(none)'}</div>,
}))

const deferred = <T,>() => {
  let resolve: (v: T) => void = () => {}
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

beforeEach(() => {
  vi.clearAllMocks()
  history.replaceState(null, '', '/')
  localStorage.clear()
  m.me.mockResolvedValue({ authenticated: true, user: 'alice' })
  m.putSettings.mockResolvedValue({})
  m.logout.mockResolvedValue({})
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
})

const follower = () => screen.queryByTestId('fold-follower')

describe('<App> and the fold follower', () => {
  it('waits for the session\'s own folds before letting it run', async () => {
    const read = deferred<Record<string, unknown>>()
    m.getSettings.mockReturnValue(read.promise)
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    expect(follower()).toBeNull()

    read.resolve({ collapsed_tasks: ['l1\u0000p1'] })
    expect(await screen.findByTestId('fold-follower')).toHaveTextContent('l1\u0000p1')
  })

  it('does not hand the next session the last one\'s folds', async () => {
    // Alice's read is slow and lands after she signed out; Bob's account has
    // never folded anything, so its settings carry no `collapsed_tasks` key.
    const alices = deferred<Record<string, unknown>>()
    m.getSettings.mockReturnValueOnce(alices.promise)
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await userEvent.click(screen.getByRole('tab', { name: 'Account' }))
    await userEvent.click(screen.getByRole('button', { name: /log out/i }))
    await screen.findByRole('button', { name: /sign in/i })
    alices.resolve({ collapsed_tasks: ['work\u0000alice-task'] })
    await new Promise((r) => setTimeout(r, 20))
    expect(follower()).toBeNull()

    const bobs = deferred<Record<string, unknown>>()
    m.getSettings.mockReturnValue(bobs.promise)
    m.login.mockResolvedValue({ authenticated: true, user: 'bob' })
    await userEvent.type(screen.getByLabelText('Username'), 'bob')
    await userEvent.type(screen.getByLabelText('Password'), 'secret')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await screen.findByRole('button', { name: 'Tasks' })
    expect(follower(), 'mounted before Bob\'s own read answered').toBeNull()

    bobs.resolve({})
    expect(await screen.findByTestId('fold-follower')).toHaveTextContent('(none)')
  })
})
